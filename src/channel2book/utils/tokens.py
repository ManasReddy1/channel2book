"""Token estimation utilities."""


def estimate_tokens(text: str) -> int:
    """Estimate token count from text. ~4 chars per token is standard approximation."""
    return len(text) // 4


def format_tokens(count: int) -> str:
    """Human-readable token count."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)
