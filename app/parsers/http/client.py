from __future__ import annotations

from typing import Any

import httpx
import structlog

from app.core.config import get_settings
from app.parsers.exceptions import SourceUnavailableError
from app.parsers.http.circuit_breaker import CircuitBreaker
from app.parsers.http.rate_limiter import RateLimiter
from app.parsers.http.retry import RetryPolicy

logger = structlog.get_logger(__name__)


class ResilientHttpClient:
    """HTTP client with retry, circuit breaker, and rate limiting."""

    def __init__(
        self,
        source_name: str,
        base_url: str,
        rate_limit: RateLimiter,
        retry: RetryPolicy,
        circuit: CircuitBreaker,
    ) -> None:
        self._source_name = source_name
        self._base_url = base_url
        self._rate_limit = rate_limit
        self._retry = retry
        self._circuit = circuit
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> ResilientHttpClient:
        settings = get_settings()
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(
                connect=settings.scraper_connect_timeout,
                read=settings.scraper_read_timeout,
                write=5.0,
                pool=5.0,
            ),
            headers={"User-Agent": settings.scraper_user_agent},
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        """Perform GET request with resilience mechanisms."""
        return await self._request("GET", path, **kwargs)

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        if path.startswith(("http://", "https://", "//")):
            raise ValueError(f"Absolute URLs are not allowed: {path}")
        await self._rate_limit.acquire()
        self._circuit.guard()

        async def attempt() -> httpx.Response:
            if self._client is None:
                raise RuntimeError("Client not initialized")
            try:
                response = await self._client.request(
                    method, path, **kwargs
                )
                response.raise_for_status()
                self._circuit.record_success()
                return response
            except (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.ReadError,
            ) as exc:
                self._circuit.record_failure()
                raise SourceUnavailableError(
                    f"Source {self._source_name} unavailable: {exc}"
                ) from exc
            except httpx.HTTPStatusError as exc:
                self._circuit.record_failure()
                raise

        return await self._retry.run(attempt)
