"""CLI interface: build, status, export commands."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from channel2book import __version__
from channel2book.config import load_config

app = typer.Typer(
    name="channel2book",
    help="Turn a YouTube channel into a beginner-friendly textbook.",
    no_args_is_help=True,
)
console = Console()


def _version_callback(value: bool):
    if value:
        console.print(f"channel2book v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-v", callback=_version_callback,
        is_eager=True, help="Show version and exit.",
    ),
):
    """channel2book — Turn a YouTube channel into a textbook."""
    pass


@app.command()
def build(
    channel_url: str = typer.Argument(..., help="YouTube channel URL"),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", help="TOML config file"),
    max_videos: int = typer.Option(0, "--max-videos", "-n", help="Limit number of videos (0=all)"),
    playlists: str = typer.Option(".*", "--playlists", "-p", help="Regex to filter playlists"),
    since: str = typer.Option("", "--since", help="Only videos after this date (YYYY-MM-DD)"),
    model: str = typer.Option("", "--model", "-m", help="Claude model to use"),
    budget: float = typer.Option(10.0, "--budget", "-b", help="Max budget in USD"),
    output_dir: str = typer.Option("output", "--output", "-o", help="Output directory"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Estimate cost without running LLM"),
    skip_checker: bool = typer.Option(False, "--skip-checker", help="Skip faithfulness check"),
    no_resume: bool = typer.Option(False, "--no-resume", help="Start fresh, ignore previous state"),
    formats: str = typer.Option("markdown", "--formats", "-f", help="Output formats: markdown,epub,pdf,site"),
    skip_shorts: bool = typer.Option(True, "--skip-shorts/--include-shorts", help="Skip YouTube Shorts"),
    min_duration: int = typer.Option(60, "--min-duration", help="Skip videos shorter than N seconds"),
    whisper: bool = typer.Option(False, "--whisper", help="Enable Whisper fallback for transcripts"),
):
    """Build a textbook from a YouTube channel."""
    overrides = {}
    if max_videos:
        overrides["filters.max_videos"] = max_videos
    if playlists != ".*":
        overrides["filters.playlists"] = playlists
    if since:
        overrides["filters.since"] = since
    if model:
        overrides["llm.model"] = model
    if budget != 10.0:
        overrides["llm.budget_usd"] = budget
    if output_dir != "output":
        overrides["output.output_dir"] = output_dir
    overrides["filters.skip_shorts"] = skip_shorts
    overrides["filters.min_duration"] = min_duration
    overrides["whisper.enabled"] = whisper

    config = load_config(
        config_path=config_file,
        channel_url=channel_url,
        cli_overrides=overrides,
    )
    config.dry_run = dry_run
    config.skip_checker = skip_checker
    config.resume = not no_resume
    config.output.formats = [f.strip() for f in formats.split(",")]

    from channel2book.pipeline import run_pipeline
    asyncio.run(run_pipeline(config))


@app.command()
def status(
    output_dir: str = typer.Option("output", "--output", "-o", help="Output directory"),
):
    """Show pipeline progress and cost."""
    config = load_config(cli_overrides={"output.output_dir": output_dir})

    from channel2book.pipeline import get_status
    asyncio.run(get_status(config))


@app.command()
def export(
    output_dir: str = typer.Option("output", "--output", "-o", help="Output directory"),
    formats: str = typer.Option("markdown,epub", "--formats", "-f", help="Output formats"),
):
    """Re-export output without re-running LLM stages."""
    config = load_config(cli_overrides={
        "output.output_dir": output_dir,
    })
    config.output.formats = [f.strip() for f in formats.split(",")]

    from channel2book.pipeline import run_export
    asyncio.run(run_export(config))


if __name__ == "__main__":
    app()
