"""Filename-safe slug generation."""

import re
import unicodedata


def slugify(text: str, max_length: int = 60) -> str:
    """Convert text to a filename-safe slug.

    Examples:
        "Hello World!" -> "hello-world"
        "My Video #3 (Part 1)" -> "my-video-3-part-1"
    """
    # Normalize unicode
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    # Lowercase
    text = text.lower()
    # Replace non-alphanumeric with hyphens
    text = re.sub(r"[^a-z0-9]+", "-", text)
    # Strip leading/trailing hyphens
    text = text.strip("-")
    # Collapse multiple hyphens
    text = re.sub(r"-+", "-", text)
    # Truncate
    if len(text) > max_length:
        text = text[:max_length].rstrip("-")
    return text or "untitled"
