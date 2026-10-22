"""Cost estimation per model."""

from channel2book.constants import MODEL_PRICING


def estimate_cost(
    input_tokens: int, output_tokens: int, model: str,
) -> float:
    """Calculate cost in USD for a given token usage."""
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return 0.0
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost


def format_cost(usd: float) -> str:
    """Human-readable cost string."""
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.2f}"


def estimate_pipeline_cost(
    total_transcript_tokens: int, model: str, num_videos: int,
) -> dict[str, float]:
    """Estimate total pipeline cost before running.

    Returns breakdown by stage.
    """
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet-4-20250514"])

    # Writer: input ≈ transcript tokens, output ≈ 30% of input per video
    writer_input = total_transcript_tokens
    writer_output = int(total_transcript_tokens * 0.3)
    writer_cost = estimate_cost(writer_input, writer_output, model)

    # Chapter intros + book parts: ~2K output per chapter, assume num_videos/5 chapters
    num_chapters = max(1, num_videos // 5)
    book_input = int(total_transcript_tokens * 0.1)
    book_output = num_chapters * 2000 + 5000  # chapters + preface/TOC/glossary
    book_cost = estimate_cost(book_input, book_output, model)

    # Checker (uses haiku): input ≈ section + transcript, output ≈ 1K per video
    checker_model = "claude-haiku-4-5-20251001"
    checker_input = int(total_transcript_tokens * 0.5)
    checker_output = num_videos * 1000
    checker_cost = estimate_cost(checker_input, checker_output, checker_model)

    return {
        "writer": writer_cost,
        "book_parts": book_cost,
        "checker": checker_cost,
        "total": writer_cost + book_cost + checker_cost,
    }
