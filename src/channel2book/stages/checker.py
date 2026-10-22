"""Stage 4: Checker — Faithfulness evaluation with self-healing correction."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from channel2book.config import Config
from channel2book.constants import CHECKER_MODEL, STATUS_DONE, STATUS_RUNNING
from channel2book.db import Database
from channel2book.llm.client import LLMClient
from channel2book.llm.prompts import CHECKER_EXTRACT_CLAIMS, CHECKER_VERIFY_CLAIM
from channel2book.models import CheckerClaim, PipelineState, Section
from channel2book.utils.progress import (
    console,
    create_progress,
    is_cancelled,
)
from channel2book.utils.rate_limit import RateLimiter


async def run_checker(
    config: Config, db: Database, channel_id: str, llm: LLMClient,
) -> dict:
    """Run faithfulness checker on all written sections. Returns quality stats."""
    pending = await db.get_videos_by_stage_status("checker", "pending", channel_id)
    if not pending:
        console.print("  [green]All sections already checked.[/green]")
        return {"total_claims": 0, "supported": 0, "unsupported": 0}

    console.print(f"  Checking faithfulness for [cyan]{len(pending)}[/cyan] sections...")
    limiter = RateLimiter(max_concurrent=config.llm.max_concurrent, delay=0.3)

    total_claims = 0
    supported_count = 0
    unsupported_count = 0

    with create_progress() as progress:
        task = progress.add_task("Checker", total=len(pending))

        for video_id in pending:
            if is_cancelled() or llm.is_over_budget():
                break

            section = await db.get_section(video_id)
            transcript = await db.get_transcript(video_id)
            if not section or not transcript:
                progress.advance(task)
                continue

            await db.upsert_pipeline_state(PipelineState(
                video_id=video_id, stage="checker",
                status=STATUS_RUNNING, started_at=datetime.now(),
            ))

            try:
                async with limiter:
                    claims = await _check_section(
                        llm, db, video_id, section, transcript.text,
                    )

                for claim in claims:
                    total_claims += 1
                    if claim.supported:
                        supported_count += 1
                    else:
                        unsupported_count += 1

                # Annotate section if there are unsupported claims
                unsupported = [c for c in claims if not c.supported]
                if unsupported and section.summary:
                    await _annotate_unsupported(db, video_id, section, unsupported)

                await db.upsert_pipeline_state(PipelineState(
                    video_id=video_id, stage="checker",
                    status=STATUS_DONE, completed_at=datetime.now(),
                ))

            except Exception as e:
                await db.upsert_pipeline_state(PipelineState(
                    video_id=video_id, stage="checker",
                    status="failed", error=str(e)[:500],
                    completed_at=datetime.now(),
                ))

            progress.advance(task)

    stats = {
        "total_claims": total_claims,
        "supported": supported_count,
        "unsupported": unsupported_count,
        "support_rate": supported_count / total_claims if total_claims > 0 else 1.0,
    }

    console.print(
        f"  Claims: [green]{supported_count}[/green] supported, "
        f"[red]{unsupported_count}[/red] unsupported out of {total_claims} total "
        f"([cyan]{stats['support_rate']:.0%}[/cyan] fidelity)"
    )

    return stats


async def _check_section(
    llm: LLMClient,
    db: Database,
    video_id: str,
    section: Section,
    transcript_text: str,
) -> list[CheckerClaim]:
    """Extract claims from a section and verify each against the transcript."""

    # Build section content for claim extraction
    section_content = f"{section.summary}\n\n{section.explained_simply}"

    # Step 1: Extract claims
    extract_prompt = CHECKER_EXTRACT_CLAIMS.format(section_content=section_content)
    claims_raw = await llm.complete(
        extract_prompt,
        model=CHECKER_MODEL,
        stage="checker",
        video_id=video_id,
        max_tokens=1024,
    )

    # Parse claims JSON
    try:
        start = claims_raw.find("[")
        end = claims_raw.rfind("]") + 1
        claims_list = json.loads(claims_raw[start:end])
    except (json.JSONDecodeError, ValueError):
        claims_list = []

    if not claims_list:
        return []

    # Step 2: Verify each claim against transcript
    verified_claims: list[CheckerClaim] = []

    # Truncate transcript if too long for verification
    max_transcript = transcript_text[:40000]

    for claim_text in claims_list[:20]:  # Cap at 20 claims per section
        verify_prompt = CHECKER_VERIFY_CLAIM.format(
            claim=claim_text,
            transcript=max_transcript,
        )
        result_raw = await llm.complete(
            verify_prompt,
            model=CHECKER_MODEL,
            stage="checker",
            video_id=video_id,
            max_tokens=300,
        )

        # Parse verification result
        try:
            start = result_raw.find("{")
            end = result_raw.rfind("}") + 1
            result = json.loads(result_raw[start:end])
        except (json.JSONDecodeError, ValueError):
            result = {"supported": False, "confidence": 0.5}

        claim = CheckerClaim(
            video_id=video_id,
            claim=claim_text,
            supported=result.get("supported", False),
            transcript_span=result.get("transcript_span", ""),
            timestamp_url=result.get("timestamp_url", ""),
            confidence=result.get("confidence", 0.5),
        )
        await db.insert_checker_claim(claim)
        verified_claims.append(claim)

    return verified_claims


async def _annotate_unsupported(
    db: Database,
    video_id: str,
    section: Section,
    unsupported: list[CheckerClaim],
) -> None:
    """Add [unverified] warnings to section content for unsupported claims."""
    # Add a warning note at the end of the summary
    warning_lines = [
        "\n\n> **Note:** The following claims could not be verified against the original transcript:"
    ]
    for claim in unsupported[:5]:
        warning_lines.append(f"> - {claim.claim}")

    section.summary = section.summary + "\n".join(warning_lines)
    await db.upsert_section(section)


def generate_quality_report(
    stats: dict, claims_by_video: dict[str, list[CheckerClaim]],
) -> dict:
    """Generate a quality report JSON for the book."""
    flagged = []
    for video_id, claims in claims_by_video.items():
        for c in claims:
            if not c.supported:
                flagged.append({
                    "video_id": video_id,
                    "claim": c.claim,
                    "confidence": c.confidence,
                    "transcript_span": c.transcript_span,
                })

    return {
        "total_claims": stats["total_claims"],
        "supported": stats["supported"],
        "unsupported": stats["unsupported"],
        "support_rate": stats["support_rate"],
        "flagged_claims": flagged,
    }
