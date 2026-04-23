from __future__ import annotations

import asyncio

import httpx
import pytest

from app.parsers.exceptions import (
    CircuitOpenError,
    MaxRetriesError,
    SourceUnavailableError,
)
from app.parsers.http import CircuitBreaker, RateLimiter, ResilientHttpClient, RetryPolicy


@pytest.fixture
def mock_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Mock asyncio.sleep to speed up tests."""
    sleep_calls: list[float] = []

    async def mock_sleep_fn(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", mock_sleep_fn)
    return sleep_calls


@pytest.mark.asyncio
async def test_successful_request(mock_sleep: list[float]) -> None:
    """Happy path: single successful request."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="http://test.local",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test.local")

        response = await client.get("/api/test")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_retry_on_503(mock_sleep: list[float]) -> None:
    """503 error triggers retry, eventual success."""
    attempts = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        attempts[0] += 1
        if attempts[0] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="http://test.local",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test.local")

        response = await client.get("/api/test")

        assert response.status_code == 200
        assert attempts[0] == 2
        assert mock_sleep == [1.0]


@pytest.mark.asyncio
async def test_max_retries_exceeded(mock_sleep: list[float]) -> None:
    """All retry attempts fail with 503."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="http://test.local",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test.local")

        with pytest.raises(MaxRetriesError) as exc_info:
            await client.get("/api/test")

        assert exc_info.value.attempts == 3
        assert mock_sleep == [1.0, 2.0]


@pytest.mark.asyncio
async def test_network_error_wrapped(mock_sleep: list[float]) -> None:
    """Network error wrapped in SourceUnavailableError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="kad",
        base_url="http://test.local",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test.local")

        with pytest.raises(MaxRetriesError) as exc_info:
            await client.get("/api/test")

        assert exc_info.value.attempts == 3
        assert isinstance(exc_info.value.__cause__, SourceUnavailableError)


@pytest.mark.asyncio
async def test_circuit_opens_after_failures(
    mock_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Circuit breaker opens after threshold exceeded."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)

    breaker = CircuitBreaker(window_size=5, failure_threshold=0.3, cooldown_sec=60.0)

    async with ResilientHttpClient(
        source_name="test",
        base_url="http://test.local",
        rate_limit=RateLimiter(capacity=100, refill_per_sec=100.0),
        retry=RetryPolicy(max_attempts=1, base_delay=1.0),
        circuit=breaker,
    ) as client:
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test.local")

        for _ in range(5):
            with pytest.raises(MaxRetriesError):
                await client.get("/api/test")

        with pytest.raises(CircuitOpenError):
            await client.get("/api/test")


@pytest.mark.asyncio
async def test_404_no_retry(mock_sleep: list[float]) -> None:
    """404 error does not trigger retry."""
    attempts = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        attempts[0] += 1
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="http://test.local",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test.local")

        with pytest.raises(httpx.HTTPStatusError):
            await client.get("/api/test")

        assert attempts[0] == 1
        assert len(mock_sleep) == 0


@pytest.mark.asyncio
async def test_get_rejects_absolute_http_url(mock_sleep: list[float]) -> None:
    """Absolute HTTP URLs are rejected to prevent SSRF."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="http://test.local",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test.local")

        with pytest.raises(ValueError, match="Absolute URLs are not allowed"):
            await client.get("http://attacker.com/x")


@pytest.mark.asyncio
async def test_get_rejects_absolute_https_url(mock_sleep: list[float]) -> None:
    """Absolute HTTPS URLs are rejected to prevent SSRF."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="http://test.local",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test.local")

        with pytest.raises(ValueError, match="Absolute URLs are not allowed"):
            await client.get("https://attacker.com/x")


@pytest.mark.asyncio
async def test_get_rejects_protocol_relative_url(mock_sleep: list[float]) -> None:
    """Protocol-relative URLs are rejected to prevent SSRF."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="http://test.local",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test.local")

        with pytest.raises(ValueError, match="Absolute URLs are not allowed"):
            await client.get("//attacker.com/x")
