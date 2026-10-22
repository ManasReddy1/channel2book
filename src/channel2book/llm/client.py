"""Anthropic SDK wrapper with retries, cost tracking, and budget enforcement."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Optional

from anthropic import Anthropic, APIError, RateLimitError

from channel2book.constants import MODEL_PRICING
from channel2book.db import Database
from channel2book.models import BudgetEntry
from channel2book.utils.cost import estimate_cost


class LLMClient:
    """Wrapper around Anthropic API with retries and cost tracking."""

    def __init__(
        self,
        db: Database,
        model: str = "claude-sonnet-4-20250514",
        budget_usd: float = 10.0,
    ):
        self._client = Anthropic()
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
        """Send a message to Claude and return the text response.

        Handles retries with exponential backoff and logs cost to DB.
        """
        if self.is_over_budget():
            raise BudgetExceededError(
                f"Budget exceeded: ${self._total_cost:.2f} >= ${self.budget_usd:.2f}"
            )

        use_model = model or self.model
        messages = [{"role": "user", "content": prompt}]

        for attempt in range(max_retries):
            try:
                kwargs = {
                    "model": use_model,
                    "max_tokens": max_tokens,
                    "messages": messages,
                }
                if system:
                    kwargs["system"] = system

                response = self._client.messages.create(**kwargs)

                # Track cost
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                cost = estimate_cost(input_tokens, output_tokens, use_model)
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

                return response.content[0].text

            except RateLimitError:
                wait = (2 ** attempt) + 1
                await asyncio.sleep(wait)

            except APIError as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)

        raise RuntimeError(f"Failed after {max_retries} retries")


class BudgetExceededError(Exception):
    """Raised when LLM budget is exceeded."""
    pass
