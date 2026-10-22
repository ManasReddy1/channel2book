"""Model pricing, defaults, and constants."""

# Model pricing (USD per million tokens)
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    # OpenAI
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    # Google
    "gemini/gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini/gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    # DeepSeek
    "deepseek/deepseek-chat": {"input": 0.27, "output": 1.10},
    # Local (free)
    "ollama/llama3.1:8b": {"input": 0.0, "output": 0.0},
    "ollama/qwen2.5:14b": {"input": 0.0, "output": 0.0},
    "ollama/qwen2.5:32b": {"input": 0.0, "output": 0.0},
}

# All available models for UI dropdowns
AVAILABLE_MODELS = list(MODEL_PRICING.keys())

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
