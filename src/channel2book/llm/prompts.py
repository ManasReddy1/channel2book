"""All prompt templates for LLM calls."""

# --- Writer Stage: Section Generation ---

SECTION_SYSTEM = """\
You are an expert textbook writer transforming video transcripts into clear, \
beginner-friendly educational content. Write in a warm, approachable style. \
Use simple language. When technical terms are unavoidable, define them immediately. \
Include examples. Reference specific timestamps so readers can watch the original video."""

SECTION_SINGLE_PROMPT = """\
Transform this video transcript into a textbook section.

Video Title: {video_title}
Video URL: https://www.youtube.com/watch?v={video_id}

<transcript>
{transcript}
</transcript>

Write the following sections in Markdown format:

## Summary
A 2-3 paragraph overview of what this video covers.

## Explained Simply
Re-explain the core concepts as if talking to a smart 15-year-old. Use analogies.

## Key Ideas
A numbered list of 5-8 main takeaways. For each:
- State the idea clearly
- Add a brief explanation
- Include a timestamp link like [Watch: 3:42](https://www.youtube.com/watch?v={video_id}&t=222)

## Examples
Real-world examples mentioned in the video, or your own illustrative examples.

## Glossary
Define technical terms used, formatted as:
- **Term**: Definition

## Exercises
3-5 practice questions or activities to reinforce learning.

## Watch This Part
The single most important segment to watch if short on time. Include timestamp and why.

Output ONLY the Markdown content, no preamble."""

SECTION_MAP_PROMPT = """\
Extract key ideas from this portion of a video transcript.

Video Title: {video_title}
Chunk {chunk_num} of {total_chunks}

<transcript_chunk>
{transcript_chunk}
</transcript_chunk>

For this chunk, identify:
1. Main concepts discussed (with brief explanations)
2. Key terms and definitions
3. Examples mentioned
4. Notable quotes or insights
5. Approximate timestamp context

Format as structured notes. Be thorough but concise."""

SECTION_REDUCE_PROMPT = """\
You have processed a long video transcript in {num_chunks} chunks. \
Below are the extracted notes from each chunk. Merge them into a \
complete, cohesive textbook section.

Video Title: {video_title}

{combined_results}

Now write a unified textbook section with these parts:

## Summary
## Explained Simply
## Key Ideas (5-8, with timestamp links)
## Examples
## Glossary (deduplicate terms)
## Exercises (3-5)
## Watch This Part

Output ONLY the Markdown content."""

# --- Writer Stage: Chapter Parts ---

CHAPTER_INTRO_PROMPT = """\
You are writing the introduction for a chapter titled "{chapter_title}" in a textbook.

This chapter covers the following sections:
{section_summaries}

Write a brief (2-3 paragraph) chapter introduction that:
1. Explains what the reader will learn
2. Shows how the sections connect to each other
3. Suggests a reading order if sections build on each other

Output ONLY the Markdown content."""

CHAPTER_SUMMARY_PROMPT = """\
Write a brief summary for a chapter titled "{chapter_title}".

The chapter contained these sections:
{section_summaries}

Write a 1-2 paragraph summary that captures the main takeaways. \
End with 2-3 reflection questions.

Output ONLY the Markdown content."""

# --- Writer Stage: Book Parts ---

BOOK_PREFACE_PROMPT = """\
Write a preface for a textbook titled "{book_title}".

This book was generated from the YouTube channel "{channel_name}" \
and contains {num_chapters} chapters covering {num_videos} video topics.

Chapter overview:
{chapter_list}

Write a welcoming preface (3-4 paragraphs) that:
1. Explains what this book covers
2. Who it's for (beginners)
3. How to use it
4. Acknowledges the original video creator

Output ONLY the Markdown content."""

BOOK_TOC_SYSTEM = "Generate a table of contents in Markdown format."

BOOK_GLOSSARY_PROMPT = """\
Merge and deduplicate these glossary entries from multiple chapters. \
Remove duplicates, keeping the clearest definition. Sort alphabetically.

{all_glossaries}

Output a clean Markdown glossary with entries formatted as:
- **Term**: Definition"""

BOOK_INDEX_PROMPT = """\
Generate a subject index for a textbook with these chapters and key topics:

{chapter_topics}

Create an alphabetical index of important terms and concepts, \
listing which chapter(s) they appear in. Format:

- **Term** — Chapter 1, Chapter 3
- **Term** — Chapter 2"""

BOOK_READING_PATHS_PROMPT = """\
Create two reading paths for this textbook:

Chapters:
{chapter_list}

1. **Beginner Path**: For someone completely new. Which chapters to read first, \
which to skip initially, suggested pace.

2. **Practitioner Path**: For someone with experience who wants to deepen knowledge. \
Which chapters are most valuable, what to focus on.

Output ONLY the Markdown content."""

# --- Checker Stage ---

CHECKER_EXTRACT_CLAIMS = """\
Extract all factual claims from this textbook section. A "claim" is any \
specific assertion of fact (dates, numbers, definitions, cause-effect, \
comparisons). Do NOT include opinions or hedged statements.

<section>
{section_content}
</section>

Return a JSON array of strings, one per claim. Example:
["Neural networks were invented in 1943", "GPT-4 has 1.8 trillion parameters"]"""

CHECKER_VERIFY_CLAIM = """\
Determine if this claim is supported by the transcript.

<claim>{claim}</claim>

<transcript>
{transcript}
</transcript>

Respond in this exact JSON format:
{{"supported": true/false, "transcript_span": "the exact quote that supports or contradicts", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}

If the claim is clearly supported, supported=true. If not found or contradicted, supported=false."""
