"""Pydantic models for channel2book data structures."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Channel(BaseModel):
    """A YouTube channel."""
    id: str
    handle: str = ""
    title: str = ""
    url: str = ""
    discovered_at: datetime = Field(default_factory=datetime.now)


class Playlist(BaseModel):
    """A playlist within a channel (becomes a chapter)."""
    id: str
    channel_id: str
    title: str
    position: int = 0
    is_included: bool = True
    chapter_slug: str = ""


class Video(BaseModel):
    """A single video (becomes a section)."""
    id: str
    playlist_id: str
    channel_id: str
    title: str
    description: str = ""
    duration_seconds: int = 0
    upload_date: str = ""
    position: int = 0
    is_short: bool = False
    is_included: bool = True


class Transcript(BaseModel):
    """Fetched transcript for a video."""
    video_id: str
    source: str = ""  # "manual", "auto", "whisper", "yt-dlp"
    language: str = "en"
    text: str = ""
    segments_json: str = "[]"  # JSON array of {start, duration, text}
    token_count: int = 0
    fetched_at: datetime = Field(default_factory=datetime.now)


class Section(BaseModel):
    """LLM-generated section content for a video."""
    video_id: str
    summary: str = ""
    explained_simply: str = ""
    key_ideas_json: str = "[]"
    examples: str = ""
    glossary_json: str = "{}"
    exercises: str = ""
    watch_this_part: str = ""
    model: str = ""


class CheckerClaim(BaseModel):
    """A single factual claim extracted and verified by the checker."""
    id: Optional[int] = None
    video_id: str
    claim: str
    supported: bool = False
    transcript_span: str = ""
    timestamp_url: str = ""
    confidence: float = 0.0


class BookPart(BaseModel):
    """A generated book-level or chapter-level piece (intro, summary, TOC, etc.)."""
    scope: str  # "chapter" or "book"
    scope_id: str  # playlist_id or "book"
    part_type: str  # "introduction", "summary", "toc", "preface", "glossary", "index"
    content: str = ""
    model: str = ""


class BudgetEntry(BaseModel):
    """A single cost entry in the budget ledger."""
    timestamp: datetime = Field(default_factory=datetime.now)
    stage: str
    video_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cumulative_usd: float = 0.0


class PipelineState(BaseModel):
    """Tracks the processing state of a video through a pipeline stage."""
    video_id: str
    stage: str
    status: str = "pending"
    attempt: int = 0
    error: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cost_usd: float = 0.0
