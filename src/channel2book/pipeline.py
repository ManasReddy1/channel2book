"""Pipeline orchestrator: runs 5 stages with resume, budget, and Ctrl-C safety."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from channel2book.config import Config
from channel2book.db import Database
from channel2book.llm.client import LLMClient, BudgetExceededError
from channel2book.stages.checker import run_checker
from channel2book.stages.discovery import run_discovery
from channel2book.stages.output import run_output
from channel2book.stages.transcript import run_transcripts
from channel2book.stages.writer import run_writer
from channel2book.utils.cost import estimate_pipeline_cost, format_cost
from channel2book.utils.progress import (
    console,
    is_cancelled,
    print_cost_table,
    print_error,
    print_header,
    print_success,
    print_warning,
    setup_signal_handler,
)


async def run_pipeline(config: Config) -> None:
    """Run the full 5-stage pipeline."""
    setup_signal_handler()

    db = Database(Path(config.output.output_dir) / "channel2book.db")
    await db.connect()

    try:
        # === Stage 1: Discovery ===
        print_header("Stage 1/5: Discovery")
        channel_id = await run_discovery(config, db)

        if is_cancelled():
            print_warning("Interrupted after discovery.")
            return

        # === Dry-run checkpoint ===
        if config.dry_run:
            await _print_dry_run_summary(config, db, channel_id)
            return

        # === Stage 2: Transcripts ===
        print_header("Stage 2/5: Transcripts")
        await run_transcripts(config, db, channel_id)

        if is_cancelled():
            print_warning("Interrupted after transcripts. Resume with --resume.")
            return

        # Cost estimation before LLM stages
        total_tokens = await _count_transcript_tokens(db, channel_id)
        all_videos = await db.get_videos(channel_id=channel_id, included_only=True)
        est_costs = estimate_pipeline_cost(total_tokens, config.llm.model, len(all_videos))

        console.print()
        print_cost_table(est_costs)
        console.print(f"  Budget: {format_cost(config.llm.budget_usd)}")
        console.print()

        # Initialize LLM client
        llm = LLMClient(db, model=config.llm.model, budget_usd=config.llm.budget_usd)
        await llm.init_cost()

        # === Stage 3: Writer ===
        print_header("Stage 3/5: Writer")
        try:
            await run_writer(config, db, channel_id, llm)
        except BudgetExceededError as e:
            print_warning(f"Budget exceeded during writer stage: {e}")
            print_warning("Resume later with --resume to continue from where you left off.")
            return

        if is_cancelled():
            print_warning("Interrupted after writer. Resume with --resume.")
            return

        # === Stage 4: Checker ===
        if not config.skip_checker:
            print_header("Stage 4/5: Faithfulness Check")
            try:
                stats = await run_checker(config, db, channel_id, llm)
                # Save quality report
                report_path = Path(config.output.output_dir) / "quality-report.json"
                report_path.write_text(json.dumps(stats, indent=2))
            except BudgetExceededError as e:
                print_warning(f"Budget exceeded during checker: {e}")
        else:
            console.print("[dim]Stage 4: Checker skipped (--skip-checker)[/dim]")

        if is_cancelled():
            print_warning("Interrupted after checker. Resume with --resume.")
            return

        # === Stage 5: Output ===
        print_header("Stage 5/5: Output Generation")
        output_dir = await run_output(config, db, channel_id)

        # === Done! ===
        total_cost = await db.get_total_cost()
        _print_completion_banner(config, output_dir, total_cost)

    except Exception as e:
        print_error(f"Pipeline error: {e}")
        raise
    finally:
        await db.close()


async def get_status(config: Config) -> None:
    """Print pipeline status from database."""
    db_path = Path(config.output.output_dir) / "channel2book.db"
    if not db_path.exists():
        print_warning("No pipeline database found. Run 'channel2book build' first.")
        return

    db = Database(db_path)
    await db.connect()

    try:
        from channel2book.utils.progress import print_stage_summary

        summary = await db.get_stage_summary()
        if summary:
            print_stage_summary(summary)
        else:
            print_warning("No pipeline data found.")

        total_cost = await db.get_total_cost()
        console.print(f"\n  Total cost: [bold]{format_cost(total_cost)}[/bold]")

        costs_by_stage = await db.get_cost_by_stage()
        if costs_by_stage:
            for stage, cost in costs_by_stage.items():
                console.print(f"    {stage}: {format_cost(cost)}")

    finally:
        await db.close()


async def run_export(config: Config) -> None:
    """Re-export output without re-running LLM stages."""
    db_path = Path(config.output.output_dir) / "channel2book.db"
    if not db_path.exists():
        print_warning("No pipeline database found. Run 'channel2book build' first.")
        return

    db = Database(db_path)
    await db.connect()

    try:
        # Find the channel
        async with db.conn.execute("SELECT id FROM channels LIMIT 1") as cur:
            row = await cur.fetchone()
            if not row:
                print_warning("No channel found in database.")
                return
            channel_id = row["id"]

        print_header("Re-exporting Output")
        await run_output(config, db, channel_id)
    finally:
        await db.close()


async def _print_dry_run_summary(config: Config, db: Database, channel_id: str) -> None:
    """Print what would happen without actually running LLM stages."""
    from rich.panel import Panel
    from rich.table import Table

    all_videos = await db.get_videos(channel_id=channel_id, included_only=True)
    playlists = await db.get_playlists(channel_id)

    console.print()
    console.print(Panel("[bold yellow]DRY RUN — No LLM calls will be made[/bold yellow]"))
    console.print()

    table = Table(title="Channel Overview", show_header=True)
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Videos to process", str(len(all_videos)))
    table.add_row("Playlists (chapters)", str(len(playlists)))
    table.add_row("Model", config.llm.model)
    table.add_row("Budget", format_cost(config.llm.budget_usd))
    console.print(table)
    console.print()

    # Estimate cost (assume average transcript size)
    avg_tokens = 5000  # rough estimate per video
    est = estimate_pipeline_cost(avg_tokens * len(all_videos), config.llm.model, len(all_videos))
    print_cost_table(est)

    console.print("\n[dim]Run without --dry-run to execute the pipeline.[/dim]")


async def _count_transcript_tokens(db: Database, channel_id: str) -> int:
    """Count total tokens across all transcripts."""
    total = 0
    async with db.conn.execute(
        "SELECT COALESCE(SUM(token_count), 0) as total FROM transcripts "
        "WHERE video_id IN (SELECT id FROM videos WHERE channel_id = ? AND is_included = 1)",
        (channel_id,),
    ) as cur:
        row = await cur.fetchone()
        total = row["total"] if row else 0
    return total


def _print_completion_banner(config: Config, output_dir: Path, total_cost: float) -> None:
    """Print the final success banner."""
    from rich.panel import Panel

    banner = (
        f"[bold green]Your textbook is ready![/bold green]\n\n"
        f"  Output: {output_dir}/book/\n"
        f"  Total cost: {format_cost(total_cost)}\n\n"
        f"  [dim]\"Knowledge is the bridge between curiosity and understanding.\"[/dim]\n\n"
        f"  [bold magenta]Aapki kitaab tayyar hai! — Your textbook is ready for you.[/bold magenta]"
    )
    console.print()
    console.print(Panel(banner, title="channel2book", border_style="green", expand=False))
