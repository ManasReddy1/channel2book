"""SQLite database: schema + async data access layer."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from channel2book.models import (
    BookPart,
    BudgetEntry,
    Channel,
    CheckerClaim,
    Playlist,
    PipelineState,
    Section,
    Transcript,
    Video,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    handle TEXT,
    title TEXT,
    url TEXT,
    discovered_at TEXT
);

CREATE TABLE IF NOT EXISTS playlists (
    id TEXT PRIMARY KEY,
    channel_id TEXT REFERENCES channels(id),
    title TEXT,
    position INTEGER DEFAULT 0,
    is_included INTEGER DEFAULT 1,
    chapter_slug TEXT
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    playlist_id TEXT REFERENCES playlists(id),
    channel_id TEXT REFERENCES channels(id),
    title TEXT,
    description TEXT DEFAULT '',
    duration_seconds INTEGER DEFAULT 0,
    upload_date TEXT DEFAULT '',
    position INTEGER DEFAULT 0,
    is_short INTEGER DEFAULT 0,
    is_included INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS transcripts (
    video_id TEXT PRIMARY KEY REFERENCES videos(id),
    source TEXT,
    language TEXT DEFAULT 'en',
    text TEXT,
    segments_json TEXT DEFAULT '[]',
    token_count INTEGER DEFAULT 0,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_state (
    video_id TEXT,
    stage TEXT,
    status TEXT DEFAULT 'pending',
    attempt INTEGER DEFAULT 0,
    error TEXT DEFAULT '',
    started_at TEXT,
    completed_at TEXT,
    cost_usd REAL DEFAULT 0.0,
    PRIMARY KEY (video_id, stage)
);

CREATE TABLE IF NOT EXISTS sections (
    video_id TEXT PRIMARY KEY REFERENCES videos(id),
    summary TEXT DEFAULT '',
    explained_simply TEXT DEFAULT '',
    key_ideas_json TEXT DEFAULT '[]',
    examples TEXT DEFAULT '',
    glossary_json TEXT DEFAULT '{}',
    exercises TEXT DEFAULT '',
    watch_this_part TEXT DEFAULT '',
    model TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS checker_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT REFERENCES videos(id),
    claim TEXT,
    supported INTEGER DEFAULT 0,
    transcript_span TEXT DEFAULT '',
    timestamp_url TEXT DEFAULT '',
    confidence REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS book_parts (
    scope TEXT,
    scope_id TEXT,
    part_type TEXT,
    content TEXT DEFAULT '',
    model TEXT DEFAULT '',
    PRIMARY KEY (scope, scope_id, part_type)
);

CREATE TABLE IF NOT EXISTS budget_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    stage TEXT,
    video_id TEXT DEFAULT '',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    cumulative_usd REAL DEFAULT 0.0
);
"""


class Database:
    """Async SQLite data access layer."""

    def __init__(self, db_path: str | Path = "channel2book.db"):
        self.db_path = str(db_path)
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "Database not connected. Call connect() first."
        return self._conn

    # --- Channels ---

    async def upsert_channel(self, ch: Channel) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO channels (id, handle, title, url, discovered_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ch.id, ch.handle, ch.title, ch.url, ch.discovered_at.isoformat()),
        )
        await self.conn.commit()

    async def get_channel(self, channel_id: str) -> Optional[Channel]:
        async with self.conn.execute(
            "SELECT * FROM channels WHERE id = ?", (channel_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return Channel(
                    id=row["id"], handle=row["handle"], title=row["title"],
                    url=row["url"], discovered_at=datetime.fromisoformat(row["discovered_at"]),
                )
        return None

    # --- Playlists ---

    async def upsert_playlist(self, pl: Playlist) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO playlists (id, channel_id, title, position, is_included, chapter_slug) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pl.id, pl.channel_id, pl.title, pl.position, int(pl.is_included), pl.chapter_slug),
        )
        await self.conn.commit()

    async def get_playlists(self, channel_id: str, included_only: bool = True) -> list[Playlist]:
        query = "SELECT * FROM playlists WHERE channel_id = ?"
        if included_only:
            query += " AND is_included = 1"
        query += " ORDER BY position"
        playlists = []
        async with self.conn.execute(query, (channel_id,)) as cur:
            async for row in cur:
                playlists.append(Playlist(
                    id=row["id"], channel_id=row["channel_id"], title=row["title"],
                    position=row["position"], is_included=bool(row["is_included"]),
                    chapter_slug=row["chapter_slug"],
                ))
        return playlists

    # --- Videos ---

    async def upsert_video(self, v: Video) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO videos "
            "(id, playlist_id, channel_id, title, description, duration_seconds, "
            "upload_date, position, is_short, is_included) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (v.id, v.playlist_id, v.channel_id, v.title, v.description,
             v.duration_seconds, v.upload_date, v.position, int(v.is_short), int(v.is_included)),
        )
        await self.conn.commit()

    async def get_videos(
        self, playlist_id: Optional[str] = None, channel_id: Optional[str] = None,
        included_only: bool = True,
    ) -> list[Video]:
        conditions = []
        params: list = []
        if playlist_id:
            conditions.append("playlist_id = ?")
            params.append(playlist_id)
        if channel_id:
            conditions.append("channel_id = ?")
            params.append(channel_id)
        if included_only:
            conditions.append("is_included = 1")
        where = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT * FROM videos WHERE {where} ORDER BY position"
        videos = []
        async with self.conn.execute(query, params) as cur:
            async for row in cur:
                videos.append(Video(
                    id=row["id"], playlist_id=row["playlist_id"],
                    channel_id=row["channel_id"], title=row["title"],
                    description=row["description"],
                    duration_seconds=row["duration_seconds"],
                    upload_date=row["upload_date"], position=row["position"],
                    is_short=bool(row["is_short"]), is_included=bool(row["is_included"]),
                ))
        return videos

    async def get_video(self, video_id: str) -> Optional[Video]:
        async with self.conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return Video(
                    id=row["id"], playlist_id=row["playlist_id"],
                    channel_id=row["channel_id"], title=row["title"],
                    description=row["description"],
                    duration_seconds=row["duration_seconds"],
                    upload_date=row["upload_date"], position=row["position"],
                    is_short=bool(row["is_short"]), is_included=bool(row["is_included"]),
                )
        return None

    # --- Transcripts ---

    async def upsert_transcript(self, t: Transcript) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO transcripts "
            "(video_id, source, language, text, segments_json, token_count, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (t.video_id, t.source, t.language, t.text, t.segments_json,
             t.token_count, t.fetched_at.isoformat()),
        )
        await self.conn.commit()

    async def get_transcript(self, video_id: str) -> Optional[Transcript]:
        async with self.conn.execute(
            "SELECT * FROM transcripts WHERE video_id = ?", (video_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return Transcript(
                    video_id=row["video_id"], source=row["source"],
                    language=row["language"], text=row["text"],
                    segments_json=row["segments_json"],
                    token_count=row["token_count"],
                    fetched_at=datetime.fromisoformat(row["fetched_at"]),
                )
        return None

    # --- Pipeline State ---

    async def upsert_pipeline_state(self, ps: PipelineState) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO pipeline_state "
            "(video_id, stage, status, attempt, error, started_at, completed_at, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ps.video_id, ps.stage, ps.status, ps.attempt, ps.error,
             ps.started_at.isoformat() if ps.started_at else None,
             ps.completed_at.isoformat() if ps.completed_at else None,
             ps.cost_usd),
        )
        await self.conn.commit()

    async def get_pipeline_state(self, video_id: str, stage: str) -> Optional[PipelineState]:
        async with self.conn.execute(
            "SELECT * FROM pipeline_state WHERE video_id = ? AND stage = ?",
            (video_id, stage),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return PipelineState(
                    video_id=row["video_id"], stage=row["stage"],
                    status=row["status"], attempt=row["attempt"],
                    error=row["error"],
                    started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
                    completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                    cost_usd=row["cost_usd"],
                )
        return None

    async def get_videos_by_stage_status(
        self, stage: str, status: str, channel_id: Optional[str] = None,
    ) -> list[str]:
        """Return video IDs that match stage+status."""
        query = "SELECT video_id FROM pipeline_state WHERE stage = ? AND status = ?"
        params: list = [stage, status]
        if channel_id:
            query += " AND video_id IN (SELECT id FROM videos WHERE channel_id = ?)"
            params.append(channel_id)
        ids = []
        async with self.conn.execute(query, params) as cur:
            async for row in cur:
                ids.append(row["video_id"])
        return ids

    async def init_pipeline_states(self, video_ids: list[str], stages: list[str]) -> None:
        """Create pending pipeline_state entries for videos that don't have them yet."""
        for vid in video_ids:
            for stage in stages:
                existing = await self.get_pipeline_state(vid, stage)
                if not existing:
                    await self.upsert_pipeline_state(PipelineState(video_id=vid, stage=stage))

    # --- Sections ---

    async def upsert_section(self, s: Section) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO sections "
            "(video_id, summary, explained_simply, key_ideas_json, examples, "
            "glossary_json, exercises, watch_this_part, model) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (s.video_id, s.summary, s.explained_simply, s.key_ideas_json,
             s.examples, s.glossary_json, s.exercises, s.watch_this_part, s.model),
        )
        await self.conn.commit()

    async def get_section(self, video_id: str) -> Optional[Section]:
        async with self.conn.execute(
            "SELECT * FROM sections WHERE video_id = ?", (video_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return Section(
                    video_id=row["video_id"], summary=row["summary"],
                    explained_simply=row["explained_simply"],
                    key_ideas_json=row["key_ideas_json"], examples=row["examples"],
                    glossary_json=row["glossary_json"], exercises=row["exercises"],
                    watch_this_part=row["watch_this_part"], model=row["model"],
                )
        return None

    # --- Checker Results ---

    async def insert_checker_claim(self, c: CheckerClaim) -> int:
        cursor = await self.conn.execute(
            "INSERT INTO checker_results "
            "(video_id, claim, supported, transcript_span, timestamp_url, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (c.video_id, c.claim, int(c.supported), c.transcript_span,
             c.timestamp_url, c.confidence),
        )
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def get_checker_claims(self, video_id: str) -> list[CheckerClaim]:
        claims = []
        async with self.conn.execute(
            "SELECT * FROM checker_results WHERE video_id = ? ORDER BY id", (video_id,)
        ) as cur:
            async for row in cur:
                claims.append(CheckerClaim(
                    id=row["id"], video_id=row["video_id"], claim=row["claim"],
                    supported=bool(row["supported"]),
                    transcript_span=row["transcript_span"],
                    timestamp_url=row["timestamp_url"],
                    confidence=row["confidence"],
                ))
        return claims

    # --- Book Parts ---

    async def upsert_book_part(self, bp: BookPart) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO book_parts (scope, scope_id, part_type, content, model) "
            "VALUES (?, ?, ?, ?, ?)",
            (bp.scope, bp.scope_id, bp.part_type, bp.content, bp.model),
        )
        await self.conn.commit()

    async def get_book_part(self, scope: str, scope_id: str, part_type: str) -> Optional[BookPart]:
        async with self.conn.execute(
            "SELECT * FROM book_parts WHERE scope = ? AND scope_id = ? AND part_type = ?",
            (scope, scope_id, part_type),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return BookPart(
                    scope=row["scope"], scope_id=row["scope_id"],
                    part_type=row["part_type"], content=row["content"],
                    model=row["model"],
                )
        return None

    async def get_book_parts_by_scope(self, scope: str, scope_id: str) -> list[BookPart]:
        parts = []
        async with self.conn.execute(
            "SELECT * FROM book_parts WHERE scope = ? AND scope_id = ?",
            (scope, scope_id),
        ) as cur:
            async for row in cur:
                parts.append(BookPart(
                    scope=row["scope"], scope_id=row["scope_id"],
                    part_type=row["part_type"], content=row["content"],
                    model=row["model"],
                ))
        return parts

    # --- Budget Ledger ---

    async def log_cost(self, entry: BudgetEntry) -> None:
        # Calculate cumulative
        async with self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) as total FROM budget_ledger"
        ) as cur:
            row = await cur.fetchone()
            cumulative = (row["total"] if row else 0) + entry.cost_usd

        entry.cumulative_usd = cumulative
        await self.conn.execute(
            "INSERT INTO budget_ledger "
            "(timestamp, stage, video_id, input_tokens, output_tokens, cost_usd, cumulative_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry.timestamp.isoformat(), entry.stage, entry.video_id,
             entry.input_tokens, entry.output_tokens, entry.cost_usd, entry.cumulative_usd),
        )
        await self.conn.commit()

    async def get_total_cost(self) -> float:
        async with self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) as total FROM budget_ledger"
        ) as cur:
            row = await cur.fetchone()
            return row["total"] if row else 0.0

    async def get_cost_by_stage(self) -> dict[str, float]:
        costs: dict[str, float] = {}
        async with self.conn.execute(
            "SELECT stage, SUM(cost_usd) as total FROM budget_ledger GROUP BY stage"
        ) as cur:
            async for row in cur:
                costs[row["stage"]] = row["total"]
        return costs

    # --- Stats ---

    async def get_stage_summary(self, channel_id: Optional[str] = None) -> dict[str, dict[str, int]]:
        """Get count of videos per stage per status."""
        query = "SELECT stage, status, COUNT(*) as cnt FROM pipeline_state"
        params: list = []
        if channel_id:
            query += " WHERE video_id IN (SELECT id FROM videos WHERE channel_id = ?)"
            params.append(channel_id)
        query += " GROUP BY stage, status"
        summary: dict[str, dict[str, int]] = {}
        async with self.conn.execute(query, params) as cur:
            async for row in cur:
                stage = row["stage"]
                if stage not in summary:
                    summary[stage] = {}
                summary[stage][row["status"]] = row["cnt"]
        return summary
