"""Tests for the output stage."""

import pytest

from channel2book.stages.output import _with_frontmatter, _format_section
from channel2book.models import Section, Video


def test_with_frontmatter():
    content = "# Hello\n\nSome content."
    result = _with_frontmatter(content, title="Test Title", chapter=1)
    assert result.startswith("---\n")
    assert 'title: "Test Title"' in result
    assert 'chapter: "1"' in result
    assert "generated:" in result
    assert "# Hello" in result


def test_format_section():
    section = Section(
        video_id="vid1",
        summary="Test summary",
        explained_simply="Simple explanation",
        key_ideas_json='["Idea one", "Idea two"]',
        examples="An example",
        glossary_json='{"Term": "Definition"}',
        exercises="1. Do this",
        watch_this_part="Watch at 2:00",
    )
    video = Video(id="vid1", playlist_id="p1", channel_id="c1", title="Test Video")

    result = _format_section(section, video)
    assert "# Test Video" in result
    assert "youtube.com/watch?v=vid1" in result
    assert "Test summary" in result
    assert "Simple explanation" in result
    assert "Idea one" in result
    assert "**Term**" in result
    assert "Do this" in result
    assert "Watch at 2:00" in result
