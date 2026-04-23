from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
import structlog

from app.parsers.exceptions import MaxRetriesError, SourceUnavailableError

T = TypeVar("T")
logger = structlog.get_logger(__name__)


class RetryPolicy:
    """Exponential backoff retry policy for HTTP requests."""

    def __init__(self, max_attempts: int, base_delay: float, max_delay: float = 60.0) -> None:
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._max_delay = max_delay

    async def run(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Execute function with retry on retryable errors."""
        attempt = 0
        last_error: Exception | None = None

        while attempt < self._max_attempts:
            attempt += 1
            try:
                return await fn()
            except httpx.HTTPStatusError as exc:
                if self._is_retryable_status(exc.response.status_code):
                    last_error = exc
                    if attempt < self._max_attempts:
                        await self._backoff(attempt)
                    continue
                raise
            except (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.ReadError,
                SourceUnavailableError,
            ) as exc:
                last_error = exc
                if attempt < self._max_attempts:
                    await self._backoff(attempt)
                continue

        raise MaxRetriesError(
            f"Request failed after {self._max_attempts} attempts",
            attempts=self._max_attempts,
        ) from last_error

    def _is_retryable_status(self, status: int) -> bool:
        return status >= 500 or status == 429

    async def _backoff(self, attempt: int) -> None:
        delay = min(self._base_delay * (2 ** (attempt - 1)), self._max_delay)
        await asyncio.sleep(delay)
