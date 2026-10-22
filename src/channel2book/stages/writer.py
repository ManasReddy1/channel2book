"""Stage 3: Writer — LLM-powered section, chapter, and book generation."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Optional

from channel2book.config import Config
from channel2book.constants import SHORT_TRANSCRIPT_THRESHOLD, STATUS_DONE, STATUS_RUNNING
from channel2book.db import Database
from channel2book.llm.client import LLMClient
from channel2book.llm.chunker import chunk_transcript, map_reduce_sections
from channel2book.llm.prompts import (
    BOOK_GLOSSARY_PROMPT,
    BOOK_INDEX_PROMPT,
    BOOK_PREFACE_PROMPT,
    BOOK_READING_PATHS_PROMPT,
    CHAPTER_INTRO_PROMPT,
    CHAPTER_SUMMARY_PROMPT,
    SECTION_MAP_PROMPT,
    SECTION_REDUCE_PROMPT,
    SECTION_SINGLE_PROMPT,
    SECTION_SYSTEM,
)
from channel2book.models import BookPart, PipelineState, Section
from channel2book.utils.progress import (
    console,
    create_progress,
    is_cancelled,
)
from channel2book.utils.rate_limit import RateLimiter
from channel2book.utils.tokens import estimate_tokens


async def run_writer(
    config: Config, db: Database, channel_id: str, llm: LLMClient,
) -> int:
    """Generate sections for all pending videos. Returns count completed."""
    pending = await db.get_videos_by_stage_status("writer", "pending", channel_id)
    if not pending:
        console.print("  [green]All sections already written.[/green]")
        return 0

    console.print(f"  Writing sections for [cyan]{len(pending)}[/cyan] videos...")
    limiter = RateLimiter(max_concurrent=config.llm.max_concurrent, delay=0.5)
    success_count = 0

    with create_progress() as progress:
        task = progress.add_task("Writer", total=len(pending))

        for video_id in pending:
            if is_cancelled() or llm.is_over_budget():
                break

            video = await db.get_video(video_id)
            transcript = await db.get_transcript(video_id)
            if not video or not transcript:
                progress.advance(task)
                continue

            # Check if section already exists (resume support)
            existing = await db.get_section(video_id)
            if existing and existing.summary:
                await _mark_done(db, video_id)
                success_count += 1
                progress.advance(task)
                continue

            await db.upsert_pipeline_state(PipelineState(
                video_id=video_id, stage="writer",
                status=STATUS_RUNNING, started_at=datetime.now(),
            ))

            try:
                async with limiter:
                    section = await _generate_section(
                        llm, video_id, video.title, transcript.text,
                    )
                section.model = llm.model
                await db.upsert_section(section)
                await _mark_done(db, video_id)
                success_count += 1
            except Exception as e:
                await db.upsert_pipeline_state(PipelineState(
                    video_id=video_id, stage="writer",
                    status="failed", error=str(e)[:500],
                    completed_at=datetime.now(),
                ))

            progress.advance(task)

    console.print(f"  Sections written: [green]{success_count}[/green]/{len(pending)}")

    # Generate chapter-level and book-level content
    await _generate_chapter_parts(config, db, channel_id, llm)
    await _generate_book_parts(config, db, channel_id, llm)

    return success_count


async def _generate_section(
    llm: LLMClient, video_id: str, title: str, transcript_text: str,
) -> Section:
    """Generate a section from a video transcript."""
    token_count = estimate_tokens(transcript_text)

    if token_count <= SHORT_TRANSCRIPT_THRESHOLD:
        # Single call for short transcripts
        prompt = SECTION_SINGLE_PROMPT.format(
            video_title=title,
            video_id=video_id,
            transcript=transcript_text,
        )
        result = await llm.complete(
            prompt, system=SECTION_SYSTEM,
            stage="writer", video_id=video_id, max_tokens=4096,
        )
        return _parse_section_markdown(video_id, result)
    else:
        # Map-reduce for long transcripts
        chunks = chunk_transcript(transcript_text)
        result = await map_reduce_sections(
            chunks=chunks,
            llm_client=llm,
            video_id=video_id,
            video_title=title,
            system_prompt=SECTION_SYSTEM,
            map_prompt_template=SECTION_MAP_PROMPT,
            reduce_prompt_template=SECTION_REDUCE_PROMPT,
        )
        return _parse_section_markdown(video_id, result)


def _parse_section_markdown(video_id: str, markdown: str) -> Section:
    """Parse the LLM's markdown output into a Section model."""
    sections_map = {}
    current_heading = ""
    current_content: list[str] = []

    for line in markdown.split("\n"):
        if line.startswith("## "):
            if current_heading:
                sections_map[current_heading] = "\n".join(current_content).strip()
            current_heading = line[3:].strip().lower()
            current_content = []
        else:
            current_content.append(line)

    if current_heading:
        sections_map[current_heading] = "\n".join(current_content).strip()

    # Extract glossary as JSON
    glossary = {}
    glossary_text = sections_map.get("glossary", "")
    for line in glossary_text.split("\n"):
        line = line.strip()
        if line.startswith("- **") and "**:" in line:
            parts = line.split("**:", 1)
            term = parts[0].replace("- **", "").strip()
            definition = parts[1].strip() if len(parts) > 1 else ""
            glossary[term] = definition

    # Extract key ideas as JSON list
    key_ideas = []
    ideas_text = sections_map.get("key ideas", "")
    for line in ideas_text.split("\n"):
        line = line.strip()
        if line and (line[0].isdigit() or line.startswith("- ")):
            key_ideas.append(line.lstrip("0123456789.- "))

    return Section(
        video_id=video_id,
        summary=sections_map.get("summary", ""),
        explained_simply=sections_map.get("explained simply", ""),
        key_ideas_json=json.dumps(key_ideas),
        examples=sections_map.get("examples", ""),
        glossary_json=json.dumps(glossary),
        exercises=sections_map.get("exercises", ""),
        watch_this_part=sections_map.get("watch this part", ""),
    )


async def _generate_chapter_parts(
    config: Config, db: Database, channel_id: str, llm: LLMClient,
) -> None:
    """Generate chapter intros and summaries."""
    playlists = await db.get_playlists(channel_id)

    for pl in playlists:
        if is_cancelled() or llm.is_over_budget():
            break

        # Check if already done
        existing = await db.get_book_part("chapter", pl.id, "introduction")
        if existing and existing.content:
            continue

        # Get all sections for this playlist
        videos = await db.get_videos(playlist_id=pl.id, included_only=True)
        section_summaries = []
        for v in videos:
            section = await db.get_section(v.id)
            if section and section.summary:
                section_summaries.append(f"- **{v.title}**: {section.summary[:200]}")

        if not section_summaries:
            continue

        summaries_text = "\n".join(section_summaries)

        # Chapter intro
        intro_prompt = CHAPTER_INTRO_PROMPT.format(
            chapter_title=pl.title,
            section_summaries=summaries_text,
        )
        intro = await llm.complete(
            intro_prompt, stage="writer", video_id=pl.id, max_tokens=1024,
        )
        await db.upsert_book_part(BookPart(
            scope="chapter", scope_id=pl.id,
            part_type="introduction", content=intro, model=llm.model,
        ))

        # Chapter summary
        summary_prompt = CHAPTER_SUMMARY_PROMPT.format(
            chapter_title=pl.title,
            section_summaries=summaries_text,
        )
        summary = await llm.complete(
            summary_prompt, stage="writer", video_id=pl.id, max_tokens=1024,
        )
        await db.upsert_book_part(BookPart(
            scope="chapter", scope_id=pl.id,
            part_type="summary", content=summary, model=llm.model,
        ))


async def _generate_book_parts(
    config: Config, db: Database, channel_id: str, llm: LLMClient,
) -> None:
    """Generate book-level parts: preface, glossary, index, reading paths."""
    if is_cancelled() or llm.is_over_budget():
        return

    channel = await db.get_channel(channel_id)
    playlists = await db.get_playlists(channel_id)
    all_videos = await db.get_videos(channel_id=channel_id, included_only=True)

    book_title = config.output.book_title or (channel.title if channel else "Untitled")

    # Build chapter list text
    chapter_list = "\n".join(
        f"{i+1}. {pl.title}" for i, pl in enumerate(playlists)
    )

    # Preface
    existing = await db.get_book_part("book", "book", "preface")
    if not existing or not existing.content:
        preface_prompt = BOOK_PREFACE_PROMPT.format(
            book_title=book_title,
            channel_name=channel.title if channel else "Unknown",
            num_chapters=len(playlists),
            num_videos=len(all_videos),
            chapter_list=chapter_list,
        )
        preface = await llm.complete(
            preface_prompt, stage="writer", video_id="book", max_tokens=1024,
        )
        await db.upsert_book_part(BookPart(
            scope="book", scope_id="book",
            part_type="preface", content=preface, model=llm.model,
        ))

    # Glossary: merge all chapter glossaries
    existing = await db.get_book_part("book", "book", "glossary")
    if not existing or not existing.content:
        all_glossaries = []
        for v in all_videos:
            section = await db.get_section(v.id)
            if section and section.glossary_json != "{}":
                try:
                    glossary = json.loads(section.glossary_json)
                    for term, defn in glossary.items():
                        all_glossaries.append(f"- **{term}**: {defn}")
                except json.JSONDecodeError:
                    pass

        if all_glossaries:
            glossary_prompt = BOOK_GLOSSARY_PROMPT.format(
                all_glossaries="\n".join(all_glossaries),
            )
            merged = await llm.complete(
                glossary_prompt, stage="writer", video_id="book", max_tokens=2048,
            )
            await db.upsert_book_part(BookPart(
                scope="book", scope_id="book",
                part_type="glossary", content=merged, model=llm.model,
            ))

    # Reading paths
    existing = await db.get_book_part("book", "book", "reading_paths")
    if not existing or not existing.content:
        paths_prompt = BOOK_READING_PATHS_PROMPT.format(
            chapter_list=chapter_list,
        )
        paths = await llm.complete(
            paths_prompt, stage="writer", video_id="book", max_tokens=1024,
        )
        await db.upsert_book_part(BookPart(
            scope="book", scope_id="book",
            part_type="reading_paths", content=paths, model=llm.model,
        ))

    # Index
    existing = await db.get_book_part("book", "book", "index")
    if not existing or not existing.content:
        chapter_topics = []
        for pl in playlists:
            videos = await db.get_videos(playlist_id=pl.id, included_only=True)
            topics = [v.title for v in videos[:10]]
            chapter_topics.append(f"**{pl.title}**: {', '.join(topics)}")

        index_prompt = BOOK_INDEX_PROMPT.format(
            chapter_topics="\n".join(chapter_topics),
        )
        index = await llm.complete(
            index_prompt, stage="writer", video_id="book", max_tokens=2048,
        )
        await db.upsert_book_part(BookPart(
            scope="book", scope_id="book",
            part_type="index", content=index, model=llm.model,
        ))


async def _mark_done(db: Database, video_id: str) -> None:
    await db.upsert_pipeline_state(PipelineState(
        video_id=video_id, stage="writer",
        status=STATUS_DONE, completed_at=datetime.now(),
    ))
