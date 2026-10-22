"""channel2book — Web UI

A clean Streamlit interface to build textbooks from YouTube channels.
Run: streamlit run web.py
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import streamlit as st

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from channel2book.config import Config, FilterConfig, LLMConfig, OutputConfig, WhisperConfig
from channel2book.db import Database
from channel2book.utils.cost import estimate_pipeline_cost, format_cost
from channel2book.utils.tokens import format_tokens

# --- Page Config ---
st.set_page_config(
    page_title="channel2book",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom CSS ---
st.markdown("""
<style>
    /* Main theme */
    .stApp {
        background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
    }

    /* Hero banner */
    .hero {
        text-align: center;
        padding: 2rem 0 1rem 0;
    }
    .hero h1 {
        font-size: 3rem;
        background: linear-gradient(90deg, #f9d423, #ff4e50);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        margin-bottom: 0.3rem;
    }
    .hero p {
        color: #b0b0b0;
        font-size: 1.1rem;
    }

    /* Cards */
    .stat-card {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 12px;
        padding: 1.2rem;
        text-align: center;
        backdrop-filter: blur(10px);
    }
    .stat-card h3 {
        color: #f9d423;
        font-size: 2rem;
        margin: 0;
    }
    .stat-card p {
        color: #888;
        font-size: 0.85rem;
        margin: 0;
    }

    /* Stage badges */
    .stage-done { color: #00e676; }
    .stage-running { color: #ffd740; }
    .stage-pending { color: #666; }
    .stage-failed { color: #ff5252; }

    /* Book preview */
    .book-card {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 12px;
        padding: 1.5rem;
        margin: 0.5rem 0;
    }

    /* Success banner */
    .success-banner {
        background: linear-gradient(90deg, #00c853, #00e676);
        color: #000;
        padding: 1.5rem;
        border-radius: 12px;
        text-align: center;
        font-size: 1.2rem;
        font-weight: 600;
        margin: 1rem 0;
    }

    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: rgba(15, 12, 41, 0.95);
    }

    /* Hide streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Button styling */
    .stButton > button {
        background: linear-gradient(90deg, #f9d423, #ff4e50);
        color: #000;
        font-weight: 700;
        border: none;
        border-radius: 8px;
        padding: 0.6rem 2rem;
        font-size: 1rem;
    }
    .stButton > button:hover {
        opacity: 0.9;
    }
</style>
""", unsafe_allow_html=True)


def run_async(coro):
    """Run an async function from sync Streamlit context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def search_channel(query: str) -> list[dict]:
    """Search YouTube for channels matching the query."""
    import subprocess
    try:
        result = subprocess.run(
            ["yt-dlp", f"ytsearch5:{query} channel", "--dump-json", "--flat-playlist",
             "--playlist-items", "1:5"],
            capture_output=True, text=True, timeout=30,
        )
        matches = []
        seen = set()
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                ch_url = data.get("channel_url") or data.get("uploader_url") or ""
                ch_name = data.get("channel") or data.get("uploader") or ""
                ch_id = data.get("channel_id") or data.get("uploader_id") or ""
                if ch_url and ch_id not in seen:
                    seen.add(ch_id)
                    matches.append({
                        "name": ch_name,
                        "url": ch_url,
                        "id": ch_id,
                        "subscribers": data.get("channel_follower_count", ""),
                    })
            except json.JSONDecodeError:
                continue
        return matches[:5]
    except Exception:
        return []


# --- Hero ---
st.markdown("""
<div class="hero">
    <h1>channel2book</h1>
    <p>Turn any YouTube channel into a beginner-friendly textbook</p>
</div>
""", unsafe_allow_html=True)

# --- Sidebar ---
with st.sidebar:
    st.markdown("### Settings")

    search_query = st.text_input(
        "Channel Name or URL",
        placeholder="3Blue1Brown",
        help="Type a channel name (we'll find it) or paste a full URL",
    )

    channel_url = ""

    if search_query:
        # Check if it's already a URL
        if "youtube.com" in search_query or "youtu.be" in search_query:
            channel_url = search_query
            st.success(f"Using URL directly")
        else:
            # Search for channel
            if f"search_{search_query}" not in st.session_state:
                with st.spinner(f"Searching for '{search_query}'..."):
                    st.session_state[f"search_{search_query}"] = search_channel(search_query)

            matches = st.session_state[f"search_{search_query}"]
            if matches:
                options = [f"{m['name']} ({m['url'].split('/')[-1]})" for m in matches]
                selected = st.radio(
                    "Select channel:",
                    options,
                    key=f"radio_{search_query}",
                )
                idx = options.index(selected)
                channel_url = matches[idx]["url"]
                subs = matches[idx].get("subscribers")
                info = f"**{matches[idx]['name']}**"
                if subs:
                    info += f" — {subs:,} subscribers" if isinstance(subs, int) else f" — {subs} subscribers"
                st.markdown(info)
            else:
                st.warning("No channels found. Try a different name or paste the URL.")

    st.markdown("---")

    max_videos = st.slider("Max Videos", 0, 100, 10, help="0 = unlimited")
    budget = st.slider("Budget (USD)", 1.0, 50.0, 10.0, step=1.0)
    model = st.selectbox("Model", [
        "claude-sonnet-4-20250514",
        "claude-haiku-4-5-20251001",
    ])

    st.markdown("---")
    st.markdown("#### Filters")
    playlist_filter = st.text_input("Playlist regex", ".*", help="Filter playlists by name")
    skip_shorts = st.checkbox("Skip Shorts", True)
    min_duration = st.number_input("Min duration (sec)", 0, 3600, 60)
    skip_checker = st.checkbox("Skip faithfulness check", False)

    st.markdown("---")
    st.markdown("#### Output")
    formats = st.multiselect("Formats", ["markdown", "epub", "pdf", "site"], default=["markdown"])

    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not has_api_key:
        st.warning("Set ANTHROPIC_API_KEY env var for LLM stages")

    st.markdown("---")
    st.markdown(
        "<p style='color:#666;font-size:0.75rem;text-align:center;'>"
        "Built with Claude | MIT License</p>",
        unsafe_allow_html=True,
    )


# --- Main Tabs ---
tab_build, tab_status, tab_browse = st.tabs(["Build", "Pipeline Status", "Browse Book"])

OUTPUT_DIR = Path("output")

# ============ BUILD TAB ============
with tab_build:
    col1, col2 = st.columns([2, 1])

    with col1:
        if channel_url:
            st.markdown(f"**Channel:** `{channel_url}`")

            # Build config
            config = Config(
                channel_url=channel_url,
                filters=FilterConfig(
                    playlists=playlist_filter,
                    max_videos=max_videos,
                    skip_shorts=skip_shorts,
                    min_duration=min_duration,
                ),
                llm=LLMConfig(model=model, budget_usd=budget),
                output=OutputConfig(formats=formats, output_dir=str(OUTPUT_DIR)),
            )

            c1, c2, c3 = st.columns(3)
            dry_run = c1.button("Dry Run", use_container_width=True, help="Estimate cost only")
            full_run = c2.button("Build Book", use_container_width=True, type="primary")
            view_status = c3.button("Refresh Status", use_container_width=True)

            if dry_run:
                config.dry_run = True
                config.skip_checker = skip_checker

                with st.spinner("Discovering channel..."):
                    from channel2book.stages.discovery import run_discovery
                    from channel2book.db import Database

                    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                    db = Database(OUTPUT_DIR / "channel2book.db")
                    run_async(db.connect())
                    try:
                        channel_id = run_async(run_discovery(config, db))
                        all_videos = run_async(db.get_videos(channel_id=channel_id, included_only=True))
                        playlists = run_async(db.get_playlists(channel_id))

                        # Stats cards
                        sc1, sc2, sc3, sc4 = st.columns(4)
                        sc1.markdown(f'<div class="stat-card"><h3>{len(all_videos)}</h3><p>Videos</p></div>', unsafe_allow_html=True)
                        sc2.markdown(f'<div class="stat-card"><h3>{len(playlists)}</h3><p>Chapters</p></div>', unsafe_allow_html=True)

                        avg_tokens = 5000
                        est = estimate_pipeline_cost(avg_tokens * len(all_videos), model, len(all_videos))
                        sc3.markdown(f'<div class="stat-card"><h3>{format_cost(est["total"])}</h3><p>Est. Cost</p></div>', unsafe_allow_html=True)
                        sc4.markdown(f'<div class="stat-card"><h3>{model.split("-")[1]}</h3><p>Model</p></div>', unsafe_allow_html=True)

                        # Cost breakdown
                        st.markdown("#### Cost Breakdown")
                        cost_data = {k: f"${v:.4f}" for k, v in est.items()}
                        st.json(cost_data)

                        # Playlist list
                        st.markdown("#### Playlists (Chapters)")
                        for i, pl in enumerate(playlists[:20]):
                            vids = run_async(db.get_videos(playlist_id=pl.id, included_only=True))
                            st.markdown(f"**{i+1}.** {pl.title} — _{len(vids)} videos_")
                        if len(playlists) > 20:
                            st.caption(f"... and {len(playlists) - 20} more")

                    finally:
                        run_async(db.close())

            elif full_run:
                if not has_api_key:
                    st.error("Set ANTHROPIC_API_KEY environment variable first!")
                else:
                    config.dry_run = False
                    config.skip_checker = skip_checker

                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    log_area = st.empty()
                    logs = []

                    stages = [
                        ("Stage 1/5: Discovery", 0.1),
                        ("Stage 2/5: Transcripts", 0.3),
                        ("Stage 3/5: Writer", 0.7),
                        ("Stage 4/5: Checker", 0.85),
                        ("Stage 5/5: Output", 0.95),
                    ]

                    try:
                        from channel2book.pipeline import run_pipeline

                        status_text.markdown("**Running full pipeline...**")

                        # Run pipeline
                        run_async(run_pipeline(config))

                        progress_bar.progress(1.0)
                        status_text.empty()

                        st.markdown(
                            '<div class="success-banner">'
                            'Your textbook is ready! 📖<br>'
                            '<small>Aapki kitaab tayyar hai!</small>'
                            '</div>',
                            unsafe_allow_html=True,
                        )

                        # Show output files
                        book_dir = OUTPUT_DIR / "book"
                        if book_dir.exists():
                            md_files = list(book_dir.rglob("*.md"))
                            st.success(f"Generated {len(md_files)} markdown files in `{book_dir}/`")

                    except Exception as e:
                        st.error(f"Pipeline error: {e}")

        else:
            st.info("Enter a YouTube channel URL in the sidebar to get started.")

            # Show example
            st.markdown("#### Example")
            st.code("channel2book build https://www.youtube.com/@3Blue1Brown --max-videos 10 --dry-run", language="bash")

    with col2:
        st.markdown("#### How It Works")
        st.markdown("""
        1. **Discovery** — Finds all playlists & videos
        2. **Transcripts** — Fetches captions (3-tier fallback)
        3. **Writer** — Claude writes each section
        4. **Checker** — Verifies claims vs transcript
        5. **Output** — Markdown, EPUB, PDF, Website
        """)

        st.markdown("#### Output")
        st.markdown("""
        ```
        output/
        ├── book/
        │   ├── 00-preface/
        │   ├── 01-chapter/
        │   │   ├── 00-intro.md
        │   │   ├── 01-section.md
        │   │   └── 99-summary.md
        │   └── ZZ-glossary/
        ├── channel2book.epub
        └── quality-report.json
        ```
        """)


# ============ STATUS TAB ============
with tab_status:
    db_path = OUTPUT_DIR / "channel2book.db"
    if db_path.exists():
        db = Database(db_path)
        run_async(db.connect())

        try:
            summary = run_async(db.get_stage_summary())
            total_cost = run_async(db.get_total_cost())
            costs_by_stage = run_async(db.get_cost_by_stage())

            if summary:
                # Stage progress
                st.markdown("#### Pipeline Progress")

                for stage, counts in summary.items():
                    done = counts.get("done", 0)
                    total = sum(counts.values())
                    pct = done / total if total > 0 else 0

                    col_a, col_b = st.columns([3, 1])
                    col_a.progress(pct, text=f"{stage}: {done}/{total}")
                    status_emoji = "✅" if pct == 1.0 else ("🔄" if counts.get("running", 0) > 0 else "⏳")
                    col_b.markdown(f"### {status_emoji}")

                # Cost
                st.markdown("---")
                cc1, cc2 = st.columns(2)
                cc1.metric("Total Cost", format_cost(total_cost))

                if costs_by_stage:
                    cc2.markdown("**Cost by Stage**")
                    for stage, cost in costs_by_stage.items():
                        cc2.markdown(f"- {stage}: {format_cost(cost)}")
            else:
                st.info("No pipeline data yet. Run a build first.")

        finally:
            run_async(db.close())
    else:
        st.info("No pipeline database found. Run a build first.")


# ============ BROWSE TAB ============
with tab_browse:
    book_dir = OUTPUT_DIR / "book"
    if book_dir.exists():
        # List all chapters
        chapters = sorted([d for d in book_dir.iterdir() if d.is_dir()])

        if chapters:
            chapter_names = [d.name for d in chapters]
            selected_chapter = st.selectbox("Select Chapter", chapter_names)

            if selected_chapter:
                chapter_path = book_dir / selected_chapter
                md_files = sorted(chapter_path.glob("*.md"))

                if md_files:
                    file_names = [f.stem for f in md_files]
                    selected_file = st.selectbox("Select Section", file_names)

                    if selected_file:
                        file_path = chapter_path / f"{selected_file}.md"
                        content = file_path.read_text()

                        # Strip frontmatter
                        if content.startswith("---"):
                            end = content.find("---", 3)
                            if end > 0:
                                content = content[end + 3:].strip()

                        st.markdown(content)
                else:
                    st.info("No sections found in this chapter.")
        else:
            st.info("No chapters generated yet.")
    else:
        st.info("No book output found. Run a build first.")

    # Quality report
    report_path = OUTPUT_DIR / "quality-report.json"
    if report_path.exists():
        st.markdown("---")
        st.markdown("#### Quality Report")
        report = json.loads(report_path.read_text())
        qc1, qc2, qc3 = st.columns(3)
        qc1.metric("Total Claims", report.get("total_claims", 0))
        qc2.metric("Supported", report.get("supported", 0))
        qc3.metric("Fidelity", f"{report.get('support_rate', 0):.0%}")

        flagged = report.get("flagged_claims", [])
        if flagged:
            st.warning(f"{len(flagged)} claims flagged as unverified")
            with st.expander("View flagged claims"):
                for c in flagged:
                    st.markdown(f"- _{c['claim']}_ (confidence: {c.get('confidence', 0):.0%})")
