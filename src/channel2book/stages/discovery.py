"""Stage 1: Discovery — yt-dlp flat extraction of channel → playlists → videos."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

from channel2book.config import Config
from channel2book.db import Database
from channel2book.models import Channel, Playlist, Video
from channel2book.utils.slugify import slugify
from channel2book.utils.progress import console, print_warning
from channel2book.utils.ytdlp import run_ytdlp


async def run_discovery(config: Config, db: Database) -> str:
    """Discover channel, playlists, and videos. Returns channel_id."""

    url = config.channel_url
    console.print(f"[bold]Discovering channel:[/bold] {url}")

    # Step 1: Get channel metadata
    channel = _extract_channel_info(url)
    await db.upsert_channel(channel)
    console.print(f"  Channel: [cyan]{channel.title}[/cyan] ({channel.handle})")

    # Step 2: Get all playlists
    playlists = _extract_playlists(url, channel.id)
    playlists = _filter_playlists(playlists, config.filters.playlists)

    for i, pl in enumerate(playlists):
        pl.position = i
        pl.chapter_slug = f"{i+1:02d}-{slugify(pl.title)}"
        await db.upsert_playlist(pl)

    console.print(f"  Playlists: [cyan]{len(playlists)}[/cyan] included")

    # Step 3: Get videos per playlist
    seen_video_ids: set[str] = set()
    total_videos = 0

    for pl in playlists:
        videos = _extract_playlist_videos(pl.id, channel.id)
        position = 0
        for v in videos:
            if v.id in seen_video_ids:
                continue  # Dedup: first playlist wins
            seen_video_ids.add(v.id)

            # Apply filters
            if not _passes_filters(v, config):
                v.is_included = False

            v.playlist_id = pl.id
            v.position = position
            position += 1
            await db.upsert_video(v)
            if v.is_included:
                total_videos += 1

    # Step 4: Find orphan videos (in uploads but not in any playlist)
    orphans = _find_orphan_videos(url, channel.id, seen_video_ids)
    if orphans:
        orphan_playlist = Playlist(
            id=f"{channel.id}_orphans",
            channel_id=channel.id,
            title="Other Videos",
            position=len(playlists),
            chapter_slug=f"{len(playlists)+1:02d}-other-videos",
        )
        await db.upsert_playlist(orphan_playlist)

        for i, v in enumerate(orphans):
            if not _passes_filters(v, config):
                v.is_included = False
            v.playlist_id = orphan_playlist.id
            v.position = i
            await db.upsert_video(v)
            if v.is_included:
                total_videos += 1

        console.print(f"  Orphan videos: [cyan]{len(orphans)}[/cyan]")

    console.print(f"  Total included videos: [bold green]{total_videos}[/bold green]")

    # Step 5: Initialize pipeline states
    all_videos = await db.get_videos(channel_id=channel.id, included_only=True)
    video_ids = [v.id for v in all_videos]

    # Apply max_videos limit
    if config.filters.max_videos > 0:
        video_ids = video_ids[:config.filters.max_videos]
        # Mark excluded videos
        for v in all_videos[config.filters.max_videos:]:
            v.is_included = False
            await db.upsert_video(v)
        console.print(
            f"  [yellow]Limited to {config.filters.max_videos} videos (--max-videos)[/yellow]"
        )

    from channel2book.constants import STAGES
    await db.init_pipeline_states(video_ids, STAGES)

    return channel.id


def _extract_channel_info(url: str) -> Channel:
    """Use yt-dlp to get channel metadata."""
    result = run_ytdlp("--dump-json", "--playlist-items", "0", "--flat-playlist", url, timeout=60)

    # Try to parse channel info from the output
    channel_id = ""
    title = ""
    handle = ""

    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            channel_id = data.get("channel_id", data.get("uploader_id", ""))
            title = data.get("channel", data.get("uploader", ""))
            handle = data.get("channel_url", url).split("/")[-1]
            if channel_id:
                break
        except json.JSONDecodeError:
            continue

    if not channel_id:
        # Fallback: extract from URL
        handle = url.rstrip("/").split("/")[-1]
        channel_id = handle
        title = handle

    return Channel(id=channel_id, handle=handle, title=title, url=url)


def _extract_playlists(url: str, channel_id: str) -> list[Playlist]:
    """Extract all playlists from a channel."""
    playlists_url = url.rstrip("/") + "/playlists"
    result = run_ytdlp("--dump-json", "--flat-playlist", playlists_url)

    playlists = []
    seen_ids: set[str] = set()

    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            pl_id = data.get("id", "")
            if pl_id and pl_id not in seen_ids:
                seen_ids.add(pl_id)
                playlists.append(Playlist(
                    id=pl_id,
                    channel_id=channel_id,
                    title=data.get("title", "Untitled"),
                ))
        except json.JSONDecodeError:
            continue

    return playlists


def _extract_playlist_videos(playlist_id: str, channel_id: str) -> list[Video]:
    """Extract all videos from a playlist."""
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    result = run_ytdlp("--dump-json", "--flat-playlist", url)

    videos = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            vid = data.get("id", "")
            if vid:
                duration = data.get("duration") or 0
                videos.append(Video(
                    id=vid,
                    playlist_id=playlist_id,
                    channel_id=channel_id,
                    title=data.get("title") or "Untitled",
                    description=data.get("description") or "",
                    duration_seconds=int(duration) if duration else 0,
                    upload_date=data.get("upload_date") or "",
                    is_short=int(duration or 0) < 62 and "#shorts" in (data.get("title") or "").lower(),
                ))
        except (json.JSONDecodeError, Exception):
            continue

    return videos


def _find_orphan_videos(url: str, channel_id: str, seen_ids: set[str]) -> list[Video]:
    """Find videos in uploads that aren't in any playlist."""
    videos_url = url.rstrip("/") + "/videos"
    result = run_ytdlp("--dump-json", "--flat-playlist", videos_url)

    orphans = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            vid = data.get("id", "")
            if vid and vid not in seen_ids:
                duration = data.get("duration") or 0
                orphans.append(Video(
                    id=vid,
                    playlist_id="",
                    channel_id=channel_id,
                    title=data.get("title", "Untitled"),
                    description=data.get("description", ""),
                    duration_seconds=int(duration) if duration else 0,
                    upload_date=data.get("upload_date", ""),
                ))
        except json.JSONDecodeError:
            continue

    return orphans


def _filter_playlists(playlists: list[Playlist], pattern: str) -> list[Playlist]:
    """Filter playlists by regex pattern."""
    if pattern == ".*":
        return playlists
    try:
        regex = re.compile(pattern, re.IGNORECASE)
        return [pl for pl in playlists if regex.search(pl.title)]
    except re.error:
        print_warning(f"Invalid playlist regex: {pattern}. Including all playlists.")
        return playlists


def _passes_filters(video: Video, config: Config) -> bool:
    """Check if a video passes the inclusion filters."""
    f = config.filters

    # Duration filter
    if video.duration_seconds > 0 and video.duration_seconds < f.min_duration:
        return False

    # Shorts filter
    if f.skip_shorts and video.is_short:
        return False

    # Date filter
    if f.since and video.upload_date:
        try:
            since_date = f.since.replace("-", "")
            if video.upload_date < since_date:
                return False
        except (ValueError, AttributeError):
            pass

    return True
