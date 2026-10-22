"""Model pricing, defaults, and constants."""

# Claude model pricing (USD per million tokens) as of 2025
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {
        "input": 3.00,
        "output": 15.00,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.00,
    },
}

# Defaults
DEFAULT_MODEL = "claude-sonnet-4-20250514"
CHECKER_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_CONCURRENT = 5
DEFAULT_BUDGET_USD = 10.0
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_MIN_DURATION = 60
DEFAULT_DELAY_BETWEEN_REQUESTS = 1.0

# Token limits
MAX_CONTEXT_TOKENS = 180_000  # Claude's context minus headroom
CHUNK_TARGET_TOKENS = 6_000   # Target size for transcript chunks
CHUNK_OVERLAP_TOKENS = 500    # Overlap between chunks
SHORT_TRANSCRIPT_THRESHOLD = 8_000  # Below this, single LLM call

# Pipeline stages (in order)
STAGES = ["discovery", "transcript", "writer", "checker", "output"]

# Stage status values
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
