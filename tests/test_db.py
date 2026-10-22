"""Tests for the SQLite database layer."""

import pytest
from datetime import datetime

from channel2book.models import (
    BudgetEntry, Channel, CheckerClaim, Playlist, PipelineState,
    Section, Transcript, Video, BookPart,
)


@pytest.mark.asyncio
async def test_upsert_and_get_channel(db):
    ch = Channel(id="UC123", handle="@test", title="Test Channel", url="https://youtube.com/@test")
    await db.upsert_channel(ch)
    got = await db.get_channel("UC123")
    assert got is not None
    assert got.title == "Test Channel"
    assert got.handle == "@test"


@pytest.mark.asyncio
async def test_upsert_and_get_playlist(db):
    ch = Channel(id="UC123", handle="@test", title="Test")
    await db.upsert_channel(ch)

    pl = Playlist(id="PL1", channel_id="UC123", title="Playlist One", position=0)
    await db.upsert_playlist(pl)

    playlists = await db.get_playlists("UC123")
    assert len(playlists) == 1
    assert playlists[0].title == "Playlist One"


@pytest.mark.asyncio
async def test_upsert_and_get_video(db):
    v = Video(
        id="vid1", playlist_id="PL1", channel_id="UC123",
        title="Test Video", duration_seconds=300,
    )
    await db.upsert_video(v)
    got = await db.get_video("vid1")
    assert got is not None
    assert got.title == "Test Video"
    assert got.duration_seconds == 300


@pytest.mark.asyncio
async def test_get_videos_filter(db):
    for i in range(3):
        v = Video(id=f"v{i}", playlist_id="PL1", channel_id="UC1",
                  title=f"Video {i}", is_included=i != 2)
        await db.upsert_video(v)

    included = await db.get_videos(channel_id="UC1", included_only=True)
    assert len(included) == 2

    all_vids = await db.get_videos(channel_id="UC1", included_only=False)
    assert len(all_vids) == 3


@pytest.mark.asyncio
async def test_transcript_upsert_and_get(db):
    t = Transcript(video_id="vid1", source="manual", text="Hello world", token_count=2)
    await db.upsert_transcript(t)
    got = await db.get_transcript("vid1")
    assert got is not None
    assert got.text == "Hello world"
    assert got.source == "manual"


@pytest.mark.asyncio
async def test_pipeline_state_lifecycle(db):
    ps = PipelineState(video_id="vid1", stage="writer", status="pending")
    await db.upsert_pipeline_state(ps)

    got = await db.get_pipeline_state("vid1", "writer")
    assert got is not None
    assert got.status == "pending"

    # Update to running
    ps.status = "running"
    ps.started_at = datetime.now()
    await db.upsert_pipeline_state(ps)

    got = await db.get_pipeline_state("vid1", "writer")
    assert got.status == "running"

    # Get by status
    pending = await db.get_videos_by_stage_status("writer", "pending")
    assert "vid1" not in pending
    running = await db.get_videos_by_stage_status("writer", "running")
    assert "vid1" in running


@pytest.mark.asyncio
async def test_init_pipeline_states(db):
    await db.init_pipeline_states(["v1", "v2"], ["discovery", "transcript"])

    s1 = await db.get_pipeline_state("v1", "discovery")
    assert s1 is not None
    assert s1.status == "pending"

    s2 = await db.get_pipeline_state("v2", "transcript")
    assert s2 is not None
    assert s2.status == "pending"


@pytest.mark.asyncio
async def test_section_upsert_and_get(db):
    s = Section(
        video_id="vid1", summary="Test summary",
        explained_simply="Simple explanation",
        key_ideas_json='["idea1", "idea2"]',
    )
    await db.upsert_section(s)
    got = await db.get_section("vid1")
    assert got is not None
    assert got.summary == "Test summary"


@pytest.mark.asyncio
async def test_checker_claims(db):
    c = CheckerClaim(video_id="vid1", claim="Test claim", supported=True, confidence=0.9)
    claim_id = await db.insert_checker_claim(c)
    assert claim_id > 0

    claims = await db.get_checker_claims("vid1")
    assert len(claims) == 1
    assert claims[0].claim == "Test claim"
    assert claims[0].supported is True


@pytest.mark.asyncio
async def test_book_parts(db):
    bp = BookPart(scope="book", scope_id="book", part_type="preface", content="Welcome!")
    await db.upsert_book_part(bp)

    got = await db.get_book_part("book", "book", "preface")
    assert got is not None
    assert got.content == "Welcome!"

    parts = await db.get_book_parts_by_scope("book", "book")
    assert len(parts) == 1


@pytest.mark.asyncio
async def test_budget_ledger(db):
    entry = BudgetEntry(stage="writer", video_id="v1", input_tokens=100, output_tokens=50, cost_usd=0.01)
    await db.log_cost(entry)

    total = await db.get_total_cost()
    assert total == pytest.approx(0.01)

    entry2 = BudgetEntry(stage="checker", video_id="v2", input_tokens=200, output_tokens=100, cost_usd=0.02)
    await db.log_cost(entry2)

    total = await db.get_total_cost()
    assert total == pytest.approx(0.03)

    by_stage = await db.get_cost_by_stage()
    assert "writer" in by_stage
    assert "checker" in by_stage


@pytest.mark.asyncio
async def test_stage_summary(db):
    await db.upsert_pipeline_state(PipelineState(video_id="v1", stage="writer", status="done"))
    await db.upsert_pipeline_state(PipelineState(video_id="v2", stage="writer", status="pending"))
    await db.upsert_pipeline_state(PipelineState(video_id="v3", stage="writer", status="failed"))

    summary = await db.get_stage_summary()
    assert "writer" in summary
    assert summary["writer"]["done"] == 1
    assert summary["writer"]["pending"] == 1
    assert summary["writer"]["failed"] == 1
