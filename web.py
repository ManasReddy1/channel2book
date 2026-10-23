"""channel2book — Web UI

A clean Streamlit interface to build textbooks from YouTube channels.
Run: streamlit run web.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import streamlit as st

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from channel2book.config import Config, FilterConfig, LLMConfig, OutputConfig
from channel2book.constants import AVAILABLE_MODELS, MODEL_PRICING
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
    """Search YouTube for channels matching the query using yt_dlp library."""
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
    }

    matches = []
    seen = set()

    # Strategy 1: Try direct @handle resolution (e.g. "3Blue1Brown" → @3Blue1Brown)
    handle_guess = query.strip().replace(" ", "")
    if not handle_guess.startswith("@"):
        handle_guess = f"@{handle_guess}"
    try:
        with yt_dlp.YoutubeDL({**ydl_opts, "playlist_items": "1"}) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/{handle_guess}", download=False
            )
            if info:
                ch_id = info.get("channel_id") or info.get("id") or ""
                ch_name = info.get("channel") or info.get("title") or query
                ch_url = info.get("channel_url") or info.get("webpage_url") or ""
                subs = info.get("channel_follower_count")
                if ch_id and ch_id not in seen:
                    seen.add(ch_id)
                    matches.append({
                        "name": ch_name,
                        "url": ch_url,
                        "id": ch_id,
                        "subscribers": subs,
                    })
    except Exception:
        pass

    # Strategy 2: Video search — extract unique channels from results
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch10:{query}", download=False)
            for entry in (result or {}).get("entries", []):
                ch_url = entry.get("channel_url") or entry.get("uploader_url") or ""
                ch_name = entry.get("channel") or entry.get("uploader") or ""
                ch_id = entry.get("channel_id") or entry.get("uploader_id") or ""
                if ch_url and ch_id and ch_id not in seen:
                    seen.add(ch_id)
                    matches.append({
                        "name": ch_name,
                        "url": ch_url,
                        "id": ch_id,
                        "subscribers": entry.get("channel_follower_count"),
                    })
    except Exception:
        pass

    return matches[:8]


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

    # Model selector with pricing info
    model_labels = []
    for m in AVAILABLE_MODELS:
        p = MODEL_PRICING.get(m, {})
        inp = p.get("input", 0)
        if inp == 0:
            model_labels.append(f"{m}  (FREE - local)")
        else:
            model_labels.append(f"{m}  (${inp:.2f}/${p.get('output', 0):.2f} per 1M)")
    selected_label = st.selectbox("Model", model_labels)
    model = AVAILABLE_MODELS[model_labels.index(selected_label)]

    # Show provider-specific API key hint
    if model.startswith("ollama/"):
        st.success("Local model — no API key needed")
    elif model.startswith("gemini/"):
        has_key = bool(os.environ.get("GEMINI_API_KEY"))
        if not has_key:
            st.info("Set `GEMINI_API_KEY` env var")
    elif model.startswith("deepseek/"):
        has_key = bool(os.environ.get("DEEPSEEK_API_KEY"))
        if not has_key:
            st.info("Set `DEEPSEEK_API_KEY` env var")
    elif "gpt" in model:
        has_key = bool(os.environ.get("OPENAI_API_KEY"))
        if not has_key:
            st.info("Set `OPENAI_API_KEY` env var")
    else:
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        if not has_key:
            st.info("Set `ANTHROPIC_API_KEY` env var")

    st.markdown("---")
    with st.expander("Advanced Filters"):
        playlist_filter = st.text_input("Playlist regex", ".*")
        skip_shorts = st.checkbox("Skip Shorts", True)
        min_duration = st.number_input("Min duration (sec)", 0, 3600, 60)
        skip_checker = st.checkbox("Skip faithfulness check", False)
        formats = st.multiselect("Output formats", ["markdown", "epub", "pdf", "site"], default=["markdown"])


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

        # Run discovery when button is clicked, store results in session_state
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

                    all_videos = run_async(db.get_videos(channel_id=channel_id, included_only=False))
                    included_videos = [v for v in all_videos if v.is_included]
                    playlists = run_async(db.get_playlists(channel_id, included_only=False))

                    # Get per-playlist video counts
                    playlist_data = []
                    for pl in playlists:
                        pl_vids = run_async(db.get_videos(playlist_id=pl.id, included_only=False))
                        playlist_data.append({"id": pl.id, "title": pl.title, "count": len(pl_vids)})

                    # Save everything to session_state so it survives reruns
                    st.session_state["discovery"] = {
                        "channel_url": channel_url,
                        "total_videos": len(all_videos),
                        "included_count": len(included_videos),
                        "playlists": playlist_data,
                    }
                    # Initialize all playlist checkboxes to selected
                    for pd in playlist_data:
                        st.session_state[f"pl_{pd['id']}"] = True

                finally:
                    run_async(db.close())

        # Show results if we have discovery data (persists across checkbox clicks)
        discovery = st.session_state.get("discovery")
        if discovery and discovery.get("channel_url") == channel_url and not full_run:
            total_video_count = discovery["total_videos"]
            included_count = discovery["included_count"]
            playlist_data = discovery["playlists"]

            # Stats row
            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.markdown(f'<div class="stat-card"><h3>{total_video_count}</h3><p>Total Videos</p></div>', unsafe_allow_html=True)
            sc2.markdown(f'<div class="stat-card"><h3>{len(playlist_data)}</h3><p>Playlists</p></div>', unsafe_allow_html=True)

            est = estimate_pipeline_cost(5000 * included_count, model, included_count)
            sc3.markdown(f'<div class="stat-card"><h3>{format_cost(est["total"])}</h3><p>Est. Cost</p></div>', unsafe_allow_html=True)

            if max_videos > 0:
                sc4.markdown(f'<div class="stat-card"><h3>{included_count}</h3><p>Will Process</p></div>', unsafe_allow_html=True)
            else:
                sc4.markdown(f'<div class="stat-card"><h3>{included_count}</h3><p>To Process</p></div>', unsafe_allow_html=True)

            # Cost table + Playlist multi-select
            st.markdown("---")
            cost_col1, cost_col2 = st.columns(2)
            with cost_col1:
                st.markdown("#### Cost Estimate")
                for stage, cost in est.items():
                    if stage != "total":
                        st.markdown(f"- **{stage.title()}**: {format_cost(cost)}")
                st.markdown(f"- **Total**: **{format_cost(est['total'])}**")
                st.caption(f"Budget limit: {format_cost(budget)}")

            with cost_col2:
                st.markdown("#### Playlists (Chapters)")
                st.caption("Select which playlists to include:")

                # Select All / Deselect All
                sel_c1, sel_c2 = st.columns(2)
                if sel_c1.button("Select All", key="sel_all", use_container_width=True):
                    for pd in playlist_data:
                        st.session_state[f"pl_{pd['id']}"] = True
                    st.rerun()
                if sel_c2.button("Deselect All", key="desel_all", use_container_width=True):
                    for pd in playlist_data:
                        st.session_state[f"pl_{pd['id']}"] = False
                    st.rerun()

                selected_playlists = []
                for pd in playlist_data[:50]:
                    key = f"pl_{pd['id']}"
                    if key not in st.session_state:
                        st.session_state[key] = True
                    checked = st.checkbox(
                        f"{pd['title']}  ({pd['count']} videos)",
                        key=key,
                    )
                    if checked:
                        selected_playlists.append(pd["id"])

                if len(playlist_data) > 50:
                    st.caption(f"+ {len(playlist_data) - 50} more playlists")

                st.session_state["selected_playlists"] = selected_playlists

                selected_vid_count = sum(
                    pd["count"] for pd in playlist_data if pd["id"] in selected_playlists
                )
                st.markdown(
                    f"**{len(selected_playlists)}/{len(playlist_data)}** playlists selected "
                    f"(**{selected_vid_count}** videos)"
                )

            if max_videos > 0 and max_videos < total_video_count:
                st.info(f"Processing limited to **{max_videos}** videos (set Max Videos to 0 for all)")

        if full_run:
            # Check if API key is available for the selected model
            needs_key = True
            key_name = "ANTHROPIC_API_KEY"
            if model.startswith("ollama/"):
                needs_key = False
            elif model.startswith("gemini/"):
                key_name = "GEMINI_API_KEY"
            elif model.startswith("deepseek/"):
                key_name = "DEEPSEEK_API_KEY"
            elif "gpt" in model:
                key_name = "OPENAI_API_KEY"

            if needs_key and not os.environ.get(key_name):
                st.error(f"Set `{key_name}` environment variable first!")
            else:
                config.dry_run = False
                config.skip_checker = skip_checker if 'skip_checker' in dir() else False

                # Apply playlist selection if available
                if "selected_playlists" in st.session_state:
                    config.selected_playlists = st.session_state["selected_playlists"]

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
