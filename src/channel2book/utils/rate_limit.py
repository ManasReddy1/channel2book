"""Semaphore-based concurrency + delay for rate limiting."""

from __future__ import annotations

import asyncio
from typing import Optional


class RateLimiter:
    """Controls concurrent access with optional delay between calls."""

    def __init__(self, max_concurrent: int = 5, delay: float = 0.5):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._delay = delay
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        await self._semaphore.acquire()
        async with self._lock:
            if self._delay > 0:
                await asyncio.sleep(self._delay)

    def release(self) -> None:
        self._semaphore.release()

    async def __aenter__(self) -> "RateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *args) -> None:
        self.release()
