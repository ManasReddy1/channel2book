"""Stage 2: Transcript fetching — 3-tier fallback with caching."""

from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime
from typing import Optional

from channel2book.config import Config
from channel2book.constants import STATUS_DONE, STATUS_FAILED, STATUS_RUNNING
from channel2book.db import Database
from channel2book.models import PipelineState, Transcript
from channel2book.utils.progress import (
    console,
    create_progress,
    is_cancelled,
    print_warning,
)
from channel2book.utils.rate_limit import RateLimiter
from channel2book.utils.tokens import estimate_tokens


async def run_transcripts(
    config: Config, db: Database, channel_id: str,
) -> int:
    """Fetch transcripts for all pending videos. Returns count of successful fetches."""
    pending = await db.get_videos_by_stage_status("transcript", "pending", channel_id)
    if not pending:
        console.print("  [green]All transcripts already fetched.[/green]")
        return 0

    console.print(f"  Fetching transcripts for [cyan]{len(pending)}[/cyan] videos...")

    limiter = RateLimiter(max_concurrent=3, delay=1.0)
    success_count = 0

    with create_progress() as progress:
        task = progress.add_task("Transcripts", total=len(pending))

        for video_id in pending:
            if is_cancelled():
                break

            video = await db.get_video(video_id)
            if not video:
                progress.advance(task)
                continue

            # Check if already cached
            existing = await db.get_transcript(video_id)
            if existing:
                await _mark_done(db, video_id)
                success_count += 1
                progress.advance(task)
                continue

            # Mark as running
            await db.upsert_pipeline_state(PipelineState(
                video_id=video_id, stage="transcript",
                status=STATUS_RUNNING, started_at=datetime.now(),
            ))

            async with limiter:
                transcript = await _fetch_transcript(video_id, config)

            if transcript:
                transcript.token_count = estimate_tokens(transcript.text)
                await db.upsert_transcript(transcript)
                await _mark_done(db, video_id)
                success_count += 1
            else:
                await db.upsert_pipeline_state(PipelineState(
                    video_id=video_id, stage="transcript",
                    status=STATUS_FAILED, error="All methods failed",
                    completed_at=datetime.now(),
                ))

            progress.advance(task)

    console.print(f"  Transcripts fetched: [green]{success_count}[/green]/{len(pending)}")
    return success_count


async def _fetch_transcript(video_id: str, config: Config) -> Optional[Transcript]:
    """Try 3 methods to get a transcript, with exponential backoff."""

    # Method 1: youtube-transcript-api (fastest, no download)
    transcript = await _try_youtube_transcript_api(video_id)
    if transcript:
        return transcript

    # Method 2: yt-dlp subtitle extraction
    transcript = await _try_ytdlp_subtitles(video_id)
    if transcript:
        return transcript

    # Method 3: faster-whisper (local, slow, optional)
    if config.whisper.enabled:
        transcript = await _try_whisper(video_id, config.whisper.model_size)
        if transcript:
            return transcript

    return None


async def _try_youtube_transcript_api(video_id: str) -> Optional[Transcript]:
    """Try youtube-transcript-api: manual > auto > translated."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        # Try manual captions first, then auto-generated
        for lang_prefs in [["en"], ["en-US", "en-GB"]]:
            try:
                entries = YouTubeTranscriptApi.get_transcript(video_id, languages=lang_prefs)
                text = " ".join(e["text"] for e in entries)
                segments = json.dumps([
                    {"start": e["start"], "duration": e["duration"], "text": e["text"]}
                    for e in entries
                ])
                return Transcript(
                    video_id=video_id, source="manual", language="en",
                    text=text, segments_json=segments,
                )
            except Exception:
                continue

        # Try auto-generated with translation
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            for t in transcript_list:
                if t.is_translatable:
                    translated = t.translate("en").fetch()
                    text = " ".join(e["text"] for e in translated)
                    segments = json.dumps([
                        {"start": e["start"], "duration": e["duration"], "text": e["text"]}
                        for e in translated
                    ])
                    return Transcript(
                        video_id=video_id, source="auto-translated",
                        language="en", text=text, segments_json=segments,
                    )
        except Exception:
            pass

    except ImportError:
        print_warning("youtube-transcript-api not installed. Skipping.")
    except Exception:
        pass

    return None


async def _try_ytdlp_subtitles(video_id: str) -> Optional[Transcript]:
    """Try yt-dlp to extract subtitles."""
    import tempfile
    import os
    from channel2book.utils.ytdlp import get_ytdlp_cmd

    url = f"https://www.youtube.com/watch?v={video_id}"
    ytdlp_cmd = get_ytdlp_cmd()

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "subs")
        try:
            proc = await asyncio.create_subprocess_exec(
                *ytdlp_cmd, "--write-auto-sub", "--sub-lang", "en",
                "--skip-download", "--sub-format", "json3",
                "-o", out_path, url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=60)

            # Look for the subtitle file
            for f in os.listdir(tmpdir):
                if f.endswith(".json3") or f.endswith(".json"):
                    sub_path = os.path.join(tmpdir, f)
                    with open(sub_path) as fh:
                        data = json.load(fh)
                    events = data.get("events", [])
                    segments = []
                    text_parts = []
                    for event in events:
                        segs = event.get("segs", [])
                        t = "".join(s.get("utf8", "") for s in segs).strip()
                        if t:
                            text_parts.append(t)
                            segments.append({
                                "start": event.get("tStartMs", 0) / 1000,
                                "duration": event.get("dDurationMs", 0) / 1000,
                                "text": t,
                            })
                    if text_parts:
                        return Transcript(
                            video_id=video_id, source="yt-dlp", language="en",
                            text=" ".join(text_parts),
                            segments_json=json.dumps(segments),
                        )
        except Exception:
            pass

    return None


async def _try_whisper(video_id: str, model_size: str) -> Optional[Transcript]:
    """Try faster-whisper local transcription."""
    try:
        import tempfile
        import os
        from channel2book.utils.ytdlp import get_ytdlp_cmd

        url = f"https://www.youtube.com/watch?v={video_id}"
        ytdlp_cmd = get_ytdlp_cmd()

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "audio.m4a")
            proc = await asyncio.create_subprocess_exec(
                *ytdlp_cmd, "-f", "bestaudio[ext=m4a]",
                "-o", audio_path, url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=300)

            if not os.path.exists(audio_path):
                return None

            from faster_whisper import WhisperModel
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            segments_iter, info = model.transcribe(audio_path, beam_size=5)

            segments = []
            text_parts = []
            for seg in segments_iter:
                text_parts.append(seg.text.strip())
                segments.append({
                    "start": seg.start,
                    "duration": seg.end - seg.start,
                    "text": seg.text.strip(),
                })

            if text_parts:
                return Transcript(
                    video_id=video_id, source="whisper", language="en",
                    text=" ".join(text_parts),
                    segments_json=json.dumps(segments),
                )
    except ImportError:
        print_warning("faster-whisper not installed. Skipping whisper transcription.")
    except Exception:
        pass

    return None


async def _mark_done(db: Database, video_id: str) -> None:
    await db.upsert_pipeline_state(PipelineState(
        video_id=video_id, stage="transcript",
        status=STATUS_DONE, completed_at=datetime.now(),
    ))
