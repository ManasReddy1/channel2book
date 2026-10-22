"""Tests for the discovery stage."""

import pytest

from channel2book.config import Config, FilterConfig
from channel2book.models import Video
from channel2book.stages.discovery import _passes_filters, _filter_playlists
from channel2book.models import Playlist


def test_passes_filters_duration():
    config = Config(filters=FilterConfig(min_duration=120))
    short = Video(id="v1", playlist_id="p1", channel_id="c1", title="Short", duration_seconds=60)
    long = Video(id="v2", playlist_id="p1", channel_id="c1", title="Long", duration_seconds=300)

    assert not _passes_filters(short, config)
    assert _passes_filters(long, config)


def test_passes_filters_shorts():
    config = Config(filters=FilterConfig(skip_shorts=True))
    short = Video(id="v1", playlist_id="p1", channel_id="c1", title="Short #shorts", is_short=True)
    normal = Video(id="v2", playlist_id="p1", channel_id="c1", title="Normal", is_short=False)

    assert not _passes_filters(short, config)
    assert _passes_filters(normal, config)


def test_passes_filters_since():
    config = Config(filters=FilterConfig(since="2024-06-01"))
    old = Video(id="v1", playlist_id="p1", channel_id="c1", title="Old", upload_date="20240101")
    new = Video(id="v2", playlist_id="p1", channel_id="c1", title="New", upload_date="20240701")

    assert not _passes_filters(old, config)
    assert _passes_filters(new, config)


def test_filter_playlists_all():
    playlists = [
        Playlist(id="p1", channel_id="c1", title="Introduction"),
        Playlist(id="p2", channel_id="c1", title="Advanced Topics"),
    ]
    result = _filter_playlists(playlists, ".*")
    assert len(result) == 2


def test_filter_playlists_regex():
    playlists = [
        Playlist(id="p1", channel_id="c1", title="Introduction to ML"),
        Playlist(id="p2", channel_id="c1", title="Advanced Python"),
        Playlist(id="p3", channel_id="c1", title="ML Deep Dive"),
    ]
    result = _filter_playlists(playlists, "ML")
    assert len(result) == 2
    assert result[0].title == "Introduction to ML"
    assert result[1].title == "ML Deep Dive"
