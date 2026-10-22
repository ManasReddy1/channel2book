# Architecture

## Pipeline Flow

```
Discovery → Transcripts → [DRY-RUN] → Writer → Checker → Output
```

Each stage is idempotent. The `pipeline_state` table tracks `(video_id, stage, status)`.
Status values: `pending → running → done` (or `failed`).

## SQLite Data Model

| Table | Purpose |
|-------|---------|
| channels | Channel metadata |
| playlists | Playlists (→ chapters) |
| videos | Videos (→ sections) |
| transcripts | Cached transcript text + segments |
| pipeline_state | Per-video-per-stage progress |
| sections | LLM-generated section content |
| checker_results | Factual claim verification |
| book_parts | Chapter intros, book preface, glossary |
| budget_ledger | Token usage and cost tracking |

## Key Design Decisions

1. **No external frameworks** — lightweight asyncio orchestrator over SQLite state
2. **Deterministic resume** — `pipeline_state` is the checkpoint system
3. **Map-reduce for long transcripts** — chunk → map → reduce/merge
4. **Budget guard** — check cost before every LLM call
5. **Graceful Ctrl-C** — current task finishes, state saved, resume later
