"""Tests for the transcript stage (unit tests only, no network)."""

import pytest

from channel2book.utils.tokens import estimate_tokens


def test_estimate_tokens():
    text = "Hello world, this is a test sentence."
    tokens = estimate_tokens(text)
    # ~37 chars / 4 ≈ 9
    assert 5 <= tokens <= 15


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0
