"""Utility to run yt-dlp reliably, whether installed as binary or Python module."""

from __future__ import annotations

import shutil
import subprocess
import sys


def get_ytdlp_cmd() -> list[str]:
    """Return the command to invoke yt-dlp.

    Prefers the binary if on PATH, falls back to `python3 -m yt_dlp`.
    """
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def run_ytdlp(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run yt-dlp with the given arguments and return the result."""
    cmd = get_ytdlp_cmd() + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
