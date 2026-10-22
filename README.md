# channel2book

Turn a YouTube channel into a beginner-friendly textbook. Each playlist becomes a chapter, each video becomes a section.

## Quick Start

```bash
# Install
pip install -e .

# Dry run (no LLM calls, just estimates)
channel2book build https://www.youtube.com/@aiDotEngineer --max-videos 5 --dry-run

# Full run
export ANTHROPIC_API_KEY=sk-ant-...
channel2book build https://www.youtube.com/@aiDotEngineer --max-videos 5 --budget 5.0

# Check progress
channel2book status

# Re-export without re-running LLM
channel2book export --formats markdown,epub
```

## Features

- **Playlist = Chapter, Video = Section** — natural book structure from YouTube organization
- **Claude-powered writing** — summaries, "explained simply", key ideas with timestamps, glossary, exercises
- **Faithfulness checker** — extracts factual claims and verifies each against the original transcript
- **4 output formats** — Markdown, EPUB, PDF, static MkDocs site
- **Resume-safe** — interrupt with Ctrl-C anytime, continue later with `--resume`
- **Budget-aware** — set a spending cap, get cost estimates before any LLM calls
- **3-tier transcripts** — youtube-transcript-api > yt-dlp subtitles > Whisper (optional)
- **SQLite state** — all progress cached, never reprocess completed work

## Pipeline

```
Stage 1: Discovery    yt-dlp flat extraction → playlists → videos
Stage 2: Transcripts  3-tier fallback with caching
     --- DRY-RUN checkpoint (--dry-run stops here) ---
Stage 3: Writer       Claude generates sections, chapters, book parts
Stage 4: Checker      Faithfulness eval: claims vs transcript
Stage 5: Output       Markdown + EPUB + PDF + MkDocs site
```

## CLI Options

```
channel2book build <URL> [OPTIONS]

  --max-videos, -n    Limit number of videos (0=all)
  --playlists, -p     Regex to filter playlists
  --since             Only videos after date (YYYY-MM-DD)
  --model, -m         Claude model (default: claude-sonnet-4-20250514)
  --budget, -b        Max budget in USD (default: $10)
  --output, -o        Output directory (default: output/)
  --formats, -f       Output formats: markdown,epub,pdf,site
  --dry-run           Estimate cost without running LLM
  --skip-checker      Skip faithfulness verification
  --no-resume         Start fresh, ignore previous state
  --whisper           Enable Whisper fallback for transcripts
  --skip-shorts       Skip YouTube Shorts (default: true)
  --min-duration      Skip videos shorter than N seconds (default: 60)
```

## Output Structure

```
output/
├── book/
│   ├── 00-preface/00-preface.md
│   ├── 01-chapter-slug/
│   │   ├── 00-introduction.md
│   │   ├── 01-section-slug.md
│   │   └── 99-chapter-summary.md
│   ├── ZZ-appendix-glossary/00-glossary.md
│   └── ZZ-appendix-index/00-index.md
├── site/                          # MkDocs HTML
├── channel2book.epub
├── channel2book.pdf
└── quality-report.json
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check src/

# Type check
mypy src/
```

## Architecture

- **SQLite as source of truth** — all state in `channel2book.db`, re-export anytime
- **Async pipeline** — concurrent LLM calls bounded by semaphore
- **Map-reduce for long videos** — chunk transcript, process independently, merge
- **Deterministic resume** — `pipeline_state` table tracks every video through every stage

## License

MIT
