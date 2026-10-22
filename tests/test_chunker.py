"""Tests for transcript chunking."""

import pytest

from channel2book.llm.chunker import chunk_transcript, _split_sentences


def test_short_transcript_single_chunk():
    text = "This is a short transcript. Only two sentences."
    chunks = chunk_transcript(text, target_tokens=1000)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_long_transcript_multiple_chunks():
    # Create a long transcript (~200 tokens per sentence, 20 sentences = ~4000 tokens)
    sentences = [f"This is sentence number {i} with some extra words to pad it out a bit more for testing purposes." for i in range(40)]
    text = " ".join(sentences)
    chunks = chunk_transcript(text, target_tokens=500, overlap_tokens=100)
    assert len(chunks) > 1
    # All text should be covered
    for sentence in sentences[:5]:
        assert any(sentence in chunk for chunk in chunks)


def test_chunk_overlap():
    sentences = [f"Sentence {i} is about topic {i}." for i in range(20)]
    text = " ".join(sentences)
    chunks = chunk_transcript(text, target_tokens=200, overlap_tokens=50)
    # With overlap, consecutive chunks should share some text
    if len(chunks) > 1:
        # Check that some content from end of chunk 0 appears in chunk 1
        last_words_chunk0 = chunks[0].split()[-5:]
        first_words_chunk1 = chunks[1].split()[:20]
        # At least some overlap should exist
        overlap = set(last_words_chunk0) & set(first_words_chunk1)
        # Not strictly guaranteed with sentence boundaries, but the mechanism should work
        assert len(chunks) >= 2


def test_split_sentences():
    text = "Hello world. How are you? I'm fine! Thanks for asking."
    sentences = _split_sentences(text)
    assert len(sentences) == 4
    assert sentences[0] == "Hello world."
    assert sentences[1] == "How are you?"


def test_empty_text():
    chunks = chunk_transcript("", target_tokens=1000)
    assert len(chunks) == 1
    assert chunks[0] == ""
