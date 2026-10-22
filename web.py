"""channel2book — Web UI

A clean Streamlit interface to build textbooks from YouTube channels.
Run: streamlit run web.py
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import streamlit as st

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from channel2book.config import Config, FilterConfig, LLMConfig, OutputConfig
from channel2book.db import Database
from channel2book.utils.cost import estimate_pipeline_cost, format_cost

# --- Page Config ---
st.set_page_config(
    page_title="channel2book",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- YouTube-style CSS ---
st.markdown("""
<style>
    .stApp { background-color: #f9f9f9; }

    .hero {
        text-align: center;
        padding: 1.5rem 0 0.5rem 0;
        border-bottom: 3px solid #ff0000;
        margin-bottom: 1.5rem;
    }
    .hero h1 {
        font-size: 2.5rem;
        color: #282828;
        font-weight: 800;
        margin-bottom: 0.2rem;
    }
    .hero h1 span { color: #ff0000; }
    .hero p { color: #606060; font-size: 1rem; }

    .stat-card {
        background: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 12px;
        padding: 1rem;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    .stat-card h3 { color: #ff0000; font-size: 1.8rem; margin: 0; }
    .stat-card p { color: #606060; font-size: 0.8rem; margin: 0; }

    .playlist-row {
        background: #ffffff;
        border: 1px solid #e5e5e5;
        border-radius: 8px;
        padding: 0.6rem 1rem;
        margin: 0.3rem 0;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .playlist-row .pl-title { color: #282828; font-weight: 500; }
    .playlist-row .pl-count {
        background: #ff0000;
        color: #fff;
        padding: 0.15rem 0.6rem;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }

    .success-banner {
        background: #ff0000;
        color: #fff;
        padding: 1.5rem;
        border-radius: 12px;
        text-align: center;
        font-size: 1.3rem;
        font-weight: 700;
        margin: 1rem 0;
    }

    [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e0e0e0; }
    [data-testid="stSidebar"] * { color: #282828 !important; }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    .stButton > button[kind="primary"] {
        background: #ff0000 !important;
        color: #fff !important;
        border: none;
        font-weight: 700;
    }
    .stButton > button {
        border: 1px solid #d0d0d0;
        border-radius: 20px;
        font-weight: 600;
        color: #282828;
    }
    .stButton > button:hover { border-color: #ff0000; }

    .stTabs [data-baseweb="tab"] { color: #606060; font-weight: 600; }
    .stTabs [aria-selected="true"] { color: #ff0000 !important; border-bottom-color: #ff0000 !important; }

    .stProgress > div > div > div > div { background-color: #ff0000; }
</style>
""", unsafe_allow_html=True)

OUTPUT_DIR = Path("output")


def run_async(coro):
    """Run an async function from sync Streamlit context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def search_channel(query: str) -> list[dict]:
    """Search YouTube for channels matching the query."""
    try:
        result = subprocess.run(
            ["yt-dlp", f"ytsearch5:{query}", "--dump-json", "--flat-playlist",
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
                if ch_url and ch_id and ch_id not in seen:
                    seen.add(ch_id)
                    matches.append({
                        "name": ch_name,
                        "url": ch_url,
                        "id": ch_id,
                        "subscribers": data.get("channel_follower_count"),
                    })
            except json.JSONDecodeError:
                continue
        return matches[:5]
    except Exception:
        return []


def count_playlist_videos(playlist_id: str) -> int:
    """Get actual video count for a playlist by fetching it directly."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--dump-json",
             f"https://www.youtube.com/playlist?list={playlist_id}"],
            capture_output=True, text=True, timeout=60,
        )
        return len([l for l in result.stdout.strip().split("\n") if l.strip()])
    except Exception:
        return 0


# --- Hero ---
st.markdown("""
<div class="hero">
    <h1>channel<span>2</span>book</h1>
    <p>Turn any YouTube channel into a beginner-friendly textbook</p>
</div>
""", unsafe_allow_html=True)

# --- Sidebar ---
with st.sidebar:
    st.image("https://www.youtube.com/s/desktop/b3a5b6a2/img/favicon_144x144.png", width=40)
    st.markdown("### Settings")

    search_query = st.text_input(
        "Channel Name or URL",
        placeholder="3Blue1Brown",
        help="Type a channel name or paste a URL",
    )

    channel_url = ""
    channel_display_name = ""

    if search_query:
        if "youtube.com" in search_query or "youtu.be" in search_query:
            channel_url = search_query
            channel_display_name = search_query.split("/")[-1]
            st.success(f"URL detected")
        else:
            cache_key = f"search_{search_query}"
            if cache_key not in st.session_state:
                with st.spinner(f"Searching '{search_query}'..."):
                    st.session_state[cache_key] = search_channel(search_query)

            matches = st.session_state[cache_key]
            if matches:
                options = [f"{m['name']}" for m in matches]
                selected = st.radio("Select channel:", options, key=f"radio_{search_query}")
                idx = options.index(selected)
                channel_url = matches[idx]["url"]
                channel_display_name = matches[idx]["name"]
                subs = matches[idx].get("subscribers")
                if subs and isinstance(subs, int):
                    st.caption(f"{subs:,} subscribers")
            else:
                st.warning("No channels found. Try a different name.")

    st.markdown("---")
    max_videos = st.slider("Max Videos", 0, 200, 0, help="0 = all videos")
    budget = st.slider("Budget (USD)", 1.0, 50.0, 10.0, step=1.0)
    model = st.selectbox("Model", [
        "claude-sonnet-4-20250514",
        "claude-haiku-4-5-20251001",
    ])

    st.markdown("---")
    with st.expander("Advanced Filters"):
        playlist_filter = st.text_input("Playlist regex", ".*")
        skip_shorts = st.checkbox("Skip Shorts", True)
        min_duration = st.number_input("Min duration (sec)", 0, 3600, 60)
        skip_checker = st.checkbox("Skip faithfulness check", False)
        formats = st.multiselect("Output formats", ["markdown", "epub", "pdf", "site"], default=["markdown"])

    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not has_api_key:
        st.info("Set `ANTHROPIC_API_KEY` for LLM stages")


# --- Main ---
tab_build, tab_status, tab_browse = st.tabs(["Build", "Status", "Read Book"])


with tab_build:
    if channel_url:
        st.markdown(f"### {channel_display_name or channel_url}")

        config = Config(
            channel_url=channel_url,
            filters=FilterConfig(
                playlists=playlist_filter if 'playlist_filter' in dir() else ".*",
                max_videos=max_videos,
                skip_shorts=skip_shorts if 'skip_shorts' in dir() else True,
                min_duration=min_duration if 'min_duration' in dir() else 60,
            ),
            llm=LLMConfig(model=model, budget_usd=budget),
            output=OutputConfig(
                formats=formats if 'formats' in dir() else ["markdown"],
                output_dir=str(OUTPUT_DIR),
            ),
        )

        c1, c2 = st.columns(2)
        dry_run = c1.button("Preview & Estimate Cost", use_container_width=True)
        full_run = c2.button("Build Textbook", use_container_width=True, type="primary")

        if dry_run:
            config.dry_run = True
            config.skip_checker = skip_checker if 'skip_checker' in dir() else False

            with st.spinner("Discovering playlists & videos..."):
                from channel2book.stages.discovery import run_discovery

                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                db = Database(OUTPUT_DIR / "channel2book.db")
                run_async(db.connect())
                try:
                    channel_id = run_async(run_discovery(config, db))

                    # Get ALL videos (not filtered) for accurate counts
                    all_videos = run_async(db.get_videos(channel_id=channel_id, included_only=False))
                    included_videos = [v for v in all_videos if v.is_included]
                    playlists = run_async(db.get_playlists(channel_id))

                    total_video_count = len(all_videos)
                    included_count = len(included_videos)

                finally:
                    run_async(db.close())

            # Stats row
            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.markdown(f'<div class="stat-card"><h3>{total_video_count}</h3><p>Total Videos</p></div>', unsafe_allow_html=True)
            sc2.markdown(f'<div class="stat-card"><h3>{len(playlists)}</h3><p>Playlists</p></div>', unsafe_allow_html=True)

            est = estimate_pipeline_cost(5000 * included_count, model, included_count)
            sc3.markdown(f'<div class="stat-card"><h3>{format_cost(est["total"])}</h3><p>Est. Cost</p></div>', unsafe_allow_html=True)

            if max_videos > 0:
                sc4.markdown(f'<div class="stat-card"><h3>{included_count}</h3><p>Will Process</p></div>', unsafe_allow_html=True)
            else:
                sc4.markdown(f'<div class="stat-card"><h3>{included_count}</h3><p>To Process</p></div>', unsafe_allow_html=True)

            # Cost table
            st.markdown("---")
            cost_col1, cost_col2 = st.columns(2)
            with cost_col1:
                st.markdown("#### Cost Estimate")
                for stage, cost in est.items():
                    if stage != "total":
                        st.markdown(f"- **{stage.title()}**: {format_cost(cost)}")
                st.markdown(f"- **Total**: **{format_cost(est['total'])}**")
                st.caption(f"Budget limit: {format_cost(budget)}")

            # Playlists with REAL video counts
            with cost_col2:
                st.markdown("#### Playlists (Chapters)")
                # Use DB to get accurate per-playlist counts (all videos, not just included)
                db2 = Database(OUTPUT_DIR / "channel2book.db")
                run_async(db2.connect())
                try:
                    for i, pl in enumerate(playlists[:25]):
                        all_pl_vids = run_async(db2.get_videos(playlist_id=pl.id, included_only=False))
                        count = len(all_pl_vids)
                        st.markdown(
                            f'<div class="playlist-row">'
                            f'<span class="pl-title">{i+1}. {pl.title}</span>'
                            f'<span class="pl-count">{count} videos</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    if len(playlists) > 25:
                        st.caption(f"+ {len(playlists) - 25} more playlists")
                finally:
                    run_async(db2.close())

            if max_videos > 0 and max_videos < total_video_count:
                st.info(f"Processing limited to **{max_videos}** videos (set Max Videos to 0 for all)")

        elif full_run:
            if not has_api_key:
                st.error("Set `ANTHROPIC_API_KEY` environment variable first!")
            else:
                config.dry_run = False
                config.skip_checker = skip_checker if 'skip_checker' in dir() else False

                status_text = st.empty()
                progress_bar = st.progress(0)

                try:
                    from channel2book.pipeline import run_pipeline
                    status_text.markdown("**Running pipeline...**")
                    run_async(run_pipeline(config))
                    progress_bar.progress(1.0)
                    status_text.empty()

                    st.markdown(
                        '<div class="success-banner">'
                        'Your textbook is ready! 📖<br>'
                        'Aapki kitaab tayyar hai — ab padho aur seekho!'
                        '</div>',
                        unsafe_allow_html=True,
                    )

                    book_dir = OUTPUT_DIR / "book"
                    if book_dir.exists():
                        md_count = len(list(book_dir.rglob("*.md")))
                        st.success(f"Generated {md_count} sections in `{book_dir}/`")

                except Exception as e:
                    st.error(f"Pipeline error: {e}")
    else:
        st.markdown("""
        ### How to use
        1. Type a **channel name** in the sidebar (e.g. `3Blue1Brown`)
        2. Select the matching channel
        3. Click **Preview & Estimate Cost** to see playlists and pricing
        4. Click **Build Textbook** to generate your book

        ```bash
        # Or use the CLI:
        channel2book build https://www.youtube.com/@3Blue1Brown --max-videos 10 --dry-run
        ```
        """)


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
                st.markdown("#### Pipeline Progress")
                for stage, counts in summary.items():
                    done = counts.get("done", 0)
                    total = sum(counts.values())
                    failed = counts.get("failed", 0)
                    pct = done / total if total > 0 else 0

                    label = f"{stage}: {done}/{total}"
                    if failed:
                        label += f" ({failed} failed)"
                    st.progress(pct, text=label)

                st.markdown("---")
                mc1, mc2 = st.columns(2)
                mc1.metric("Total Cost", format_cost(total_cost))
                mc2.metric("Budget", format_cost(budget))

                if costs_by_stage:
                    st.markdown("**Cost by stage:**")
                    for stage, cost in costs_by_stage.items():
                        st.markdown(f"- {stage}: {format_cost(cost)}")
            else:
                st.info("No pipeline data yet.")
        finally:
            run_async(db.close())
    else:
        st.info("No pipeline database found. Run a build first.")


with tab_browse:
    book_dir = OUTPUT_DIR / "book"
    if book_dir.exists():
        chapters = sorted([d for d in book_dir.iterdir() if d.is_dir()])
        if chapters:
            chapter_names = [d.name for d in chapters]
            selected_chapter = st.selectbox("Chapter", chapter_names)

            if selected_chapter:
                chapter_path = book_dir / selected_chapter
                md_files = sorted(chapter_path.glob("*.md"))

                if md_files:
                    file_names = [f.stem for f in md_files]
                    selected_file = st.selectbox("Section", file_names)

                    if selected_file:
                        content = (chapter_path / f"{selected_file}.md").read_text()
                        if content.startswith("---"):
                            end = content.find("---", 3)
                            if end > 0:
                                content = content[end + 3:].strip()
                        st.markdown(content)
                else:
                    st.info("No sections in this chapter.")
        else:
            st.info("No chapters yet. Build a book first.")
    else:
        st.info("No book output. Build a book first.")

    report_path = OUTPUT_DIR / "quality-report.json"
    if report_path.exists():
        st.markdown("---")
        st.markdown("#### Quality Report")
        report = json.loads(report_path.read_text())
        qc1, qc2, qc3 = st.columns(3)
        qc1.metric("Claims", report.get("total_claims", 0))
        qc2.metric("Verified", report.get("supported", 0))
        qc3.metric("Fidelity", f"{report.get('support_rate', 0):.0%}")
