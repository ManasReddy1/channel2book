"""Configuration: TOML file + CLI flag merging."""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from channel2book.constants import (
    DEFAULT_BUDGET_USD,
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_MIN_DURATION,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    CHECKER_MODEL,
)


class FilterConfig(BaseModel):
    playlists: str = ".*"
    max_videos: int = 0
    since: str = ""
    min_duration: int = DEFAULT_MIN_DURATION
    skip_shorts: bool = True


class LLMConfig(BaseModel):
    model: str = DEFAULT_MODEL
    haiku_model: str = CHECKER_MODEL
    max_concurrent: int = DEFAULT_MAX_CONCURRENT
    budget_usd: float = DEFAULT_BUDGET_USD


class OutputConfig(BaseModel):
    formats: list[str] = Field(default_factory=lambda: ["markdown"])
    output_dir: str = DEFAULT_OUTPUT_DIR
    book_title: str = ""


class WhisperConfig(BaseModel):
    enabled: bool = False
    model_size: str = "base"


class Config(BaseModel):
    """Full configuration, merged from TOML file + CLI overrides."""
    channel_url: str = ""
    filters: FilterConfig = Field(default_factory=FilterConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    whisper: WhisperConfig = Field(default_factory=WhisperConfig)
    dry_run: bool = False
    skip_checker: bool = False
    resume: bool = True  # resume from last state by default
    selected_playlists: Optional[list[str]] = None  # None = all playlists


def load_config(
    config_path: Optional[Path] = None,
    *,
    channel_url: str = "",
    cli_overrides: Optional[dict] = None,
) -> Config:
    """Load config from TOML file and merge with CLI overrides.

    Priority: CLI flags > TOML file > defaults.
    """
    data: dict = {}

    # Load TOML if it exists
    if config_path and config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    else:
        # Check for channel2book.toml in current dir
        default_path = Path("channel2book.toml")
        if default_path.exists():
            with open(default_path, "rb") as f:
                data = tomllib.load(f)

    # Extract channel URL from TOML
    if "channel" in data:
        data["channel_url"] = data.pop("channel", {}).get("url", "")

    # CLI channel_url takes priority
    if channel_url:
        data["channel_url"] = channel_url

    # Apply CLI overrides
    if cli_overrides:
        for key, value in cli_overrides.items():
            if value is not None:
                # Handle nested keys like "filters.max_videos"
                parts = key.split(".")
                if len(parts) == 2:
                    section, field = parts
                    if section not in data:
                        data[section] = {}
                    data[section][field] = value
                else:
                    data[key] = value

    return Config(**data)
