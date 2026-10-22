"""Tests for the writer stage section parsing."""

import json
import pytest

from channel2book.stages.writer import _parse_section_markdown


def test_parse_section_markdown():
    markdown = """## Summary

This video covers machine learning basics.

## Explained Simply

Think of it like teaching a computer to learn from examples.

## Key Ideas

1. Neural networks mimic the brain
2. Training adjusts weights
3. Backpropagation is key

## Examples

Image classification is a common use case.

## Glossary

- **Neural Network**: A model inspired by the brain
- **Weight**: A learnable parameter

## Exercises

1. Build a simple neural network
2. Train it on MNIST

## Watch This Part

Watch the backpropagation explanation at 3:30."""

    section = _parse_section_markdown("vid1", markdown)

    assert section.video_id == "vid1"
    assert "machine learning" in section.summary
    assert "teaching a computer" in section.explained_simply
    assert section.examples != ""
    assert section.exercises != ""
    assert section.watch_this_part != ""

    # Check key ideas parsed
    ideas = json.loads(section.key_ideas_json)
    assert len(ideas) == 3
    assert "Neural networks" in ideas[0]

    # Check glossary parsed
    glossary = json.loads(section.glossary_json)
    assert "Neural Network" in glossary
    assert "Weight" in glossary


def test_parse_section_empty():
    section = _parse_section_markdown("vid1", "No headings here, just text.")
    assert section.video_id == "vid1"
    assert section.summary == ""
