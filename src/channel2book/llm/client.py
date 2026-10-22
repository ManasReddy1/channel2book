"""Multi-provider LLM client via litellm — supports Claude, GPT, Gemini, Ollama, and 100+ models."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

import litellm

from channel2book.db import Database
from channel2book.models import BudgetEntry

# Suppress litellm debug logs
litellm.suppress_debug_info = True


class LLMClient:
    """Universal LLM client with retries and cost tracking.

    Supports any model via litellm:
      - claude-sonnet-4-20250514     (Anthropic)
      - claude-haiku-4-5-20251001    (Anthropic)
      - gpt-4o-mini                  (OpenAI)
      - gemini/gemini-2.0-flash      (Google)
      - deepseek/deepseek-chat       (DeepSeek)
      - ollama/llama3.1:8b           (Local, free)
      - ollama/qwen2.5:14b           (Local, free)
    """

    def __init__(
        self,
        db: Database,
        model: str = "claude-sonnet-4-20250514",
        budget_usd: float = 10.0,
    ):
        self._db = db
        self.model = model
        self.budget_usd = budget_usd
        self._total_cost: float = 0.0

    async def init_cost(self) -> None:
        """Load existing cost from DB."""
        self._total_cost = await self._db.get_total_cost()

    @property
    def total_cost(self) -> float:
        return self._total_cost

    def is_over_budget(self) -> bool:
        # Local models (ollama) have no cost — never over budget
        if self.model.startswith("ollama/"):
            return False
        return self._total_cost >= self.budget_usd

    async def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        model: Optional[str] = None,
        max_tokens: int = 4096,
        stage: str = "unknown",
        video_id: str = "",
        max_retries: int = 3,
    ) -> str:
        """Send a prompt to any LLM and return the text response.

        Works with Claude, GPT, Gemini, DeepSeek, Ollama, and 100+ models.
        """
        if self.is_over_budget():
            raise BudgetExceededError(
                f"Budget exceeded: ${self._total_cost:.2f} >= ${self.budget_usd:.2f}"
            )

        use_model = model or self.model
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        for attempt in range(max_retries):
            try:
                response = litellm.completion(
                    model=use_model,
                    messages=messages,
                    max_tokens=max_tokens,
                )

                # Extract response text
                text = response.choices[0].message.content

                # Track cost (litellm calculates it for known models)
                input_tokens = response.usage.prompt_tokens or 0
                output_tokens = response.usage.completion_tokens or 0

                try:
                    cost = litellm.completion_cost(completion_response=response)
                except Exception:
                    # Fallback: estimate for unknown models (local etc.)
                    cost = 0.0

                self._total_cost += cost

                entry = BudgetEntry(
                    timestamp=datetime.now(),
                    stage=stage,
                    video_id=video_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                )
                await self._db.log_cost(entry)

                return text

            except Exception as e:
                error_str = str(e).lower()
                if "rate" in error_str and "limit" in error_str:
                    wait = (2 ** attempt) + 1
                    await asyncio.sleep(wait)
                elif attempt == max_retries - 1:
                    raise
                else:
                    await asyncio.sleep(2 ** attempt)

        raise RuntimeError(f"Failed after {max_retries} retries")


class BudgetExceededError(Exception):
    """Raised when LLM budget is exceeded."""
    pass
