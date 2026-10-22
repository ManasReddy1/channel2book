"""Stage 5: Output — Markdown, EPUB, PDF, MkDocs static site."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from channel2book.config import Config
from channel2book.constants import STATUS_DONE
from channel2book.db import Database
from channel2book.models import PipelineState
from channel2book.utils.progress import console, print_success, print_warning
from channel2book.utils.slugify import slugify


async def run_output(
    config: Config, db: Database, channel_id: str,
) -> Path:
    """Generate all output formats. Returns path to output directory."""
    output_dir = Path(config.output.output_dir)
    book_dir = output_dir / "book"
    book_dir.mkdir(parents=True, exist_ok=True)

    channel = await db.get_channel(channel_id)
    playlists = await db.get_playlists(channel_id)
    book_title = config.output.book_title or (channel.title if channel else "Untitled")

    console.print(f"  Generating output to [cyan]{output_dir}[/cyan]...")

    # --- Markdown ---
    await _write_markdown(db, playlists, channel_id, book_dir, book_title)

    # --- EPUB ---
    if "epub" in config.output.formats:
        epub_path = output_dir / "channel2book.epub"
        _generate_epub(book_dir, epub_path, book_title)

    # --- PDF ---
    if "pdf" in config.output.formats:
        pdf_path = output_dir / "channel2book.pdf"
        _generate_pdf(book_dir, pdf_path, book_title)

    # --- MkDocs site ---
    if "site" in config.output.formats:
        await _generate_mkdocs_site(db, playlists, channel_id, output_dir, book_title)

    # Mark all videos as output-done
    all_videos = await db.get_videos(channel_id=channel_id, included_only=True)
    for v in all_videos:
        await db.upsert_pipeline_state(PipelineState(
            video_id=v.id, stage="output",
            status=STATUS_DONE, completed_at=datetime.now(),
        ))

    print_success(f"  Output written to {output_dir}/")
    return output_dir


async def _write_markdown(
    db: Database,
    playlists: list,
    channel_id: str,
    book_dir: Path,
    book_title: str,
) -> None:
    """Write the full markdown book structure."""

    # Preface
    preface_dir = book_dir / "00-preface"
    preface_dir.mkdir(exist_ok=True)
    preface = await db.get_book_part("book", "book", "preface")
    (preface_dir / "00-preface.md").write_text(
        _with_frontmatter(
            preface.content if preface else f"# {book_title}\n\nWelcome to this textbook.",
            title="Preface",
            book_title=book_title,
        )
    )

    # Chapters
    for i, pl in enumerate(playlists):
        chapter_slug = pl.chapter_slug or f"{i+1:02d}-{slugify(pl.title)}"
        chapter_dir = book_dir / chapter_slug
        chapter_dir.mkdir(exist_ok=True)

        # Chapter intro
        intro = await db.get_book_part("chapter", pl.id, "introduction")
        (chapter_dir / "00-introduction.md").write_text(
            _with_frontmatter(
                intro.content if intro else f"# {pl.title}",
                title=pl.title,
                chapter=i + 1,
            )
        )

        # Sections (one per video)
        videos = await db.get_videos(playlist_id=pl.id, included_only=True)
        for j, v in enumerate(videos):
            section = await db.get_section(v.id)
            if not section:
                continue

            section_slug = f"{j+1:02d}-{slugify(v.title)}"
            content = _format_section(section, v)
            (chapter_dir / f"{section_slug}.md").write_text(
                _with_frontmatter(content, title=v.title, video_id=v.id)
            )

        # Chapter summary
        summary = await db.get_book_part("chapter", pl.id, "summary")
        if summary and summary.content:
            (chapter_dir / "99-chapter-summary.md").write_text(
                _with_frontmatter(summary.content, title=f"{pl.title} - Summary")
            )

    # Appendices
    glossary = await db.get_book_part("book", "book", "glossary")
    if glossary and glossary.content:
        glossary_dir = book_dir / "ZZ-appendix-glossary"
        glossary_dir.mkdir(exist_ok=True)
        (glossary_dir / "00-glossary.md").write_text(
            _with_frontmatter(glossary.content, title="Glossary")
        )

    index = await db.get_book_part("book", "book", "index")
    if index and index.content:
        index_dir = book_dir / "ZZ-appendix-index"
        index_dir.mkdir(exist_ok=True)
        (index_dir / "00-index.md").write_text(
            _with_frontmatter(index.content, title="Index")
        )

    reading_paths = await db.get_book_part("book", "book", "reading_paths")
    if reading_paths and reading_paths.content:
        paths_dir = book_dir / "ZZ-appendix-reading-paths"
        paths_dir.mkdir(exist_ok=True)
        (paths_dir / "00-reading-paths.md").write_text(
            _with_frontmatter(reading_paths.content, title="Reading Paths")
        )


def _format_section(section, video) -> str:
    """Format a section into clean markdown."""
    parts = [f"# {video.title}"]
    parts.append(f"\n> Watch the original: [YouTube](https://www.youtube.com/watch?v={video.id})\n")

    if section.summary:
        parts.append(f"## Summary\n\n{section.summary}")
    if section.explained_simply:
        parts.append(f"## Explained Simply\n\n{section.explained_simply}")

    # Key ideas
    try:
        ideas = json.loads(section.key_ideas_json)
        if ideas:
            parts.append("## Key Ideas\n")
            for k, idea in enumerate(ideas, 1):
                parts.append(f"{k}. {idea}")
    except json.JSONDecodeError:
        pass

    if section.examples:
        parts.append(f"\n## Examples\n\n{section.examples}")

    # Glossary
    try:
        glossary = json.loads(section.glossary_json)
        if glossary:
            parts.append("\n## Glossary\n")
            for term, defn in glossary.items():
                parts.append(f"- **{term}**: {defn}")
    except json.JSONDecodeError:
        pass

    if section.exercises:
        parts.append(f"\n## Exercises\n\n{section.exercises}")
    if section.watch_this_part:
        parts.append(f"\n## Watch This Part\n\n{section.watch_this_part}")

    return "\n".join(parts)


def _with_frontmatter(content: str, **meta) -> str:
    """Add YAML frontmatter to markdown content."""
    lines = ["---"]
    for key, value in meta.items():
        lines.append(f"{key}: \"{value}\"")
    lines.append(f"generated: \"{datetime.now().isoformat()}\"")
    lines.append("---\n")
    lines.append(content)
    return "\n".join(lines)


def _generate_epub(book_dir: Path, output_path: Path, title: str) -> None:
    """Generate EPUB using pandoc."""
    if not shutil.which("pandoc"):
        print_warning("pandoc not found. Install it for EPUB/PDF export: https://pandoc.org/installing.html")
        return

    # Collect all markdown files in order
    md_files = sorted(book_dir.rglob("*.md"))
    if not md_files:
        return

    cmd = [
        "pandoc",
        "--metadata", f"title={title}",
        "-o", str(output_path),
        *[str(f) for f in md_files],
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        print_success(f"  EPUB: {output_path}")
    except subprocess.CalledProcessError as e:
        print_warning(f"  EPUB generation failed: {e.stderr[:200] if e.stderr else 'unknown error'}")
    except FileNotFoundError:
        print_warning("  pandoc not found in PATH")


def _generate_pdf(book_dir: Path, output_path: Path, title: str) -> None:
    """Generate PDF using pandoc."""
    if not shutil.which("pandoc"):
        print_warning("pandoc not found. Skipping PDF.")
        return

    md_files = sorted(book_dir.rglob("*.md"))
    if not md_files:
        return

    cmd = [
        "pandoc",
        "--metadata", f"title={title}",
        "--pdf-engine=xelatex",
        "-o", str(output_path),
        *[str(f) for f in md_files],
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        print_success(f"  PDF: {output_path}")
    except subprocess.CalledProcessError as e:
        print_warning(f"  PDF generation failed: {e.stderr[:200] if e.stderr else 'unknown error'}")
    except FileNotFoundError:
        print_warning("  pandoc/xelatex not found")


async def _generate_mkdocs_site(
    db: Database,
    playlists: list,
    channel_id: str,
    output_dir: Path,
    book_title: str,
) -> None:
    """Generate MkDocs configuration and build static site."""
    if not shutil.which("mkdocs"):
        print_warning("mkdocs not found. Install: pip install mkdocs mkdocs-material")
        return

    # Generate mkdocs.yml
    nav = [{"Home": "index.md"}]

    for i, pl in enumerate(playlists):
        chapter_slug = pl.chapter_slug or f"{i+1:02d}-{slugify(pl.title)}"
        chapter_nav = [{"Introduction": f"{chapter_slug}/00-introduction.md"}]

        videos = await db.get_videos(playlist_id=pl.id, included_only=True)
        for j, v in enumerate(videos):
            section_slug = f"{j+1:02d}-{slugify(v.title)}"
            chapter_nav.append({v.title[:50]: f"{chapter_slug}/{section_slug}.md"})

        nav.append({pl.title: chapter_nav})

    nav.append({"Glossary": "ZZ-appendix-glossary/00-glossary.md"})

    mkdocs_config = {
        "site_name": book_title,
        "theme": {
            "name": "material",
            "palette": {"primary": "deep purple", "accent": "amber"},
            "features": ["navigation.sections", "navigation.expand", "toc.integrate"],
        },
        "nav": nav,
        "docs_dir": "book",
    }

    import yaml
    mkdocs_path = output_dir / "mkdocs.yml"

    # Write as YAML manually since we may not have PyYAML
    try:
        import yaml
        mkdocs_path.write_text(yaml.dump(mkdocs_config, default_flow_style=False))
    except ImportError:
        # Fallback: write minimal mkdocs.yml
        mkdocs_path.write_text(
            f"site_name: {book_title}\n"
            f"theme:\n  name: material\n"
            f"docs_dir: book\n"
        )

    # Create index.md if it doesn't exist
    index_path = output_dir / "book" / "index.md"
    if not index_path.exists():
        preface = await db.get_book_part("book", "book", "preface")
        index_path.write_text(preface.content if preface else f"# {book_title}")

    try:
        subprocess.run(
            ["mkdocs", "build", "-f", str(mkdocs_path), "-d", str(output_dir / "site")],
            check=True, capture_output=True, timeout=120,
            cwd=str(output_dir),
        )
        print_success(f"  Site: {output_dir / 'site'}/")
    except subprocess.CalledProcessError as e:
        print_warning(f"  MkDocs build failed: {e.stderr[:200] if e.stderr else ''}")
