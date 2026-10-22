"""Transcript chunking + map-reduce for long transcripts."""

from __future__ import annotations

import json
import re
from typing import Optional

from channel2book.constants import CHUNK_OVERLAP_TOKENS, CHUNK_TARGET_TOKENS
from channel2book.utils.tokens import estimate_tokens


def chunk_transcript(
    text: str,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> list[str]:
    """Split a transcript into overlapping chunks on sentence boundaries.

    Returns a list of text chunks, each roughly target_tokens in size,
    with overlap_tokens of overlap between consecutive chunks.
    """
    if estimate_tokens(text) <= target_tokens:
        return [text]

    # Split into sentences
    sentences = _split_sentences(text)
    if not sentences:
        return [text]

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sent_tokens = estimate_tokens(sentence)

        if current_tokens + sent_tokens > target_tokens and current_chunk:
            # Save current chunk
            chunks.append(" ".join(current_chunk))

            # Keep overlap: walk backwards to find overlap_tokens worth of sentences
            overlap_sents: list[str] = []
            overlap_count = 0
            for s in reversed(current_chunk):
                t = estimate_tokens(s)
                if overlap_count + t > overlap_tokens:
                    break
                overlap_sents.insert(0, s)
                overlap_count += t

            current_chunk = overlap_sents
            current_tokens = overlap_count

        current_chunk.append(sentence)
        current_tokens += sent_tokens

    # Don't forget the last chunk
    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, keeping them clean."""
    # Split on period/question mark/exclamation followed by space or end
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


async def map_reduce_sections(
    chunks: list[str],
    llm_client,
    video_id: str,
    video_title: str,
    system_prompt: str,
    map_prompt_template: str,
    reduce_prompt_template: str,
) -> str:
    """Process chunks with map step, then merge with reduce step.

    1. Map: Process each chunk independently → partial results
    2. Reduce: Merge all partial results into final output
    """
    from channel2book.llm.prompts import SECTION_MAP_PROMPT, SECTION_REDUCE_PROMPT

    # Map step: process each chunk
    partial_results = []
    for i, chunk in enumerate(chunks):
        prompt = map_prompt_template.format(
            chunk_num=i + 1,
            total_chunks=len(chunks),
            video_title=video_title,
            transcript_chunk=chunk,
        )
        result = await llm_client.complete(
            prompt, system=system_prompt,
            stage="writer", video_id=video_id, max_tokens=2048,
        )
        partial_results.append(result)

    # Reduce step: merge all partials
    combined = "\n\n---\n\n".join(
        f"[Chunk {i+1}/{len(chunks)}]\n{r}" for i, r in enumerate(partial_results)
    )
    reduce_prompt = reduce_prompt_template.format(
        video_title=video_title,
        num_chunks=len(chunks),
        combined_results=combined,
    )
    final = await llm_client.complete(
        reduce_prompt, system=system_prompt,
        stage="writer", video_id=video_id, max_tokens=4096,
    )
    return final
