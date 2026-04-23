from __future__ import annotations

import asyncio

import httpx
import pytest

from app.parsers.exceptions import MaxRetriesError
from app.parsers.http.retry import RetryPolicy


@pytest.fixture
def mock_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Mock asyncio.sleep to track backoff delays."""
    sleep_calls: list[float] = []

    async def mock_sleep_fn(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", mock_sleep_fn)
    return sleep_calls


@pytest.mark.asyncio
async def test_success_first_attempt(mock_sleep: list[float]) -> None:
    """Successful request on first attempt requires no retry."""
    policy = RetryPolicy(max_attempts=3, base_delay=2.0)

    async def succeed() -> str:
        return "success"

    result = await policy.run(succeed)

    assert result == "success"
    assert len(mock_sleep) == 0


@pytest.mark.asyncio
async def test_success_second_attempt(mock_sleep: list[float]) -> None:
    """Retry succeeds on second attempt with correct backoff."""
    policy = RetryPolicy(max_attempts=3, base_delay=2.0)
    attempts = [0]

    async def succeed_on_second() -> str:
        attempts[0] += 1
        if attempts[0] == 1:
            raise httpx.ConnectError("connection failed")
        return "success"

    result = await policy.run(succeed_on_second)

    assert result == "success"
    assert attempts[0] == 2
    assert mock_sleep == [2.0]


@pytest.mark.asyncio
async def test_max_retries_exhausted(mock_sleep: list[float]) -> None:
    """All retry attempts fail, raises MaxRetriesError."""
    policy = RetryPolicy(max_attempts=3, base_delay=2.0)

    async def always_fail() -> str:
        raise httpx.TimeoutException("timeout")

    with pytest.raises(MaxRetriesError) as exc_info:
        await policy.run(always_fail)

    assert exc_info.value.attempts == 3
    assert mock_sleep == [2.0, 4.0]


@pytest.mark.asyncio
async def test_4xx_fail_fast(mock_sleep: list[float]) -> None:
    """4xx errors (except 429) do not trigger retry."""
    policy = RetryPolicy(max_attempts=3, base_delay=2.0)

    async def fail_404() -> str:
        response = httpx.Response(404)
        raise httpx.HTTPStatusError(
            "not found", request=httpx.Request("GET", "http://test"), response=response
        )

    with pytest.raises(httpx.HTTPStatusError):
        await policy.run(fail_404)

    assert len(mock_sleep) == 0


@pytest.mark.asyncio
async def test_429_retries(mock_sleep: list[float]) -> None:
    """429 rate limit errors trigger retry."""
    policy = RetryPolicy(max_attempts=3, base_delay=2.0)
    attempts = [0]

    async def fail_429_then_succeed() -> str:
        attempts[0] += 1
        if attempts[0] == 1:
            response = httpx.Response(429)
            raise httpx.HTTPStatusError(
                "rate limited",
                request=httpx.Request("GET", "http://test"),
                response=response,
            )
        return "success"

    result = await policy.run(fail_429_then_succeed)

    assert result == "success"
    assert mock_sleep == [2.0]


@pytest.mark.asyncio
async def test_5xx_retries(mock_sleep: list[float]) -> None:
    """5xx server errors trigger retry."""
    policy = RetryPolicy(max_attempts=3, base_delay=2.0)
    attempts = [0]

    async def fail_503_then_succeed() -> str:
        attempts[0] += 1
        if attempts[0] <= 2:
            response = httpx.Response(503)
            raise httpx.HTTPStatusError(
                "service unavailable",
                request=httpx.Request("GET", "http://test"),
                response=response,
            )
        return "success"

    result = await policy.run(fail_503_then_succeed)

    assert result == "success"
    assert mock_sleep == [2.0, 4.0]


@pytest.mark.asyncio
async def test_exponential_backoff(mock_sleep: list[float]) -> None:
    """Backoff delays follow exponential pattern."""
    policy = RetryPolicy(max_attempts=4, base_delay=1.0)

    async def always_fail() -> str:
        raise httpx.ReadError("read error")

    with pytest.raises(MaxRetriesError):
        await policy.run(always_fail)

    assert mock_sleep == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_backoff_is_capped_at_max_delay(mock_sleep: list[float]) -> None:
    """Backoff delays are capped at max_delay to prevent exhaustion."""
    policy = RetryPolicy(max_attempts=5, base_delay=10.0, max_delay=15.0)

    async def always_fail() -> str:
        raise httpx.TimeoutException("timeout")

    with pytest.raises(MaxRetriesError):
        await policy.run(always_fail)

    # Without cap: [10.0, 20.0, 40.0, 80.0]
    # With max_delay=15.0: [10.0, 15.0, 15.0, 15.0]
    assert all(delay <= 15.0 for delay in mock_sleep)
    assert mock_sleep == [10.0, 15.0, 15.0, 15.0]
