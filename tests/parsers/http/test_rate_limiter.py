from __future__ import annotations

import asyncio
import time

import pytest

from app.parsers.http.rate_limiter import RateLimiter


@pytest.fixture
def mock_monotonic(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Mock time.monotonic to control time in tests."""
    current_time = [0.0]

    def mock_time() -> float:
        return current_time[0]

    monkeypatch.setattr(time, "monotonic", mock_time)
    return current_time


@pytest.fixture
def mock_sleep(
    monkeypatch: pytest.MonkeyPatch, mock_monotonic: list[float]
) -> list[float]:
    """Mock asyncio.sleep to track sleep calls and advance time."""
    sleep_calls: list[float] = []

    async def mock_sleep_fn(delay: float) -> None:
        sleep_calls.append(delay)
        mock_monotonic[0] += delay

    monkeypatch.setattr(asyncio, "sleep", mock_sleep_fn)
    return sleep_calls


@pytest.mark.asyncio
async def test_acquire_within_capacity(mock_monotonic: list[float]) -> None:
    """Tokens are available immediately when under capacity."""
    limiter = RateLimiter(capacity=5, refill_per_sec=2.0)

    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()


@pytest.mark.asyncio
async def test_acquire_waits_when_empty(
    mock_monotonic: list[float], mock_sleep: list[float]
) -> None:
    """Acquire blocks when tokens exhausted."""
    limiter = RateLimiter(capacity=2, refill_per_sec=1.0)

    await limiter.acquire()
    await limiter.acquire()

    await limiter.acquire()

    assert len(mock_sleep) == 1
    assert mock_sleep[0] == 1.0


@pytest.mark.asyncio
async def test_refill_adds_tokens_over_time(
    mock_monotonic: list[float], mock_sleep: list[float]
) -> None:
    """Tokens refill based on elapsed time."""
    limiter = RateLimiter(capacity=10, refill_per_sec=2.0)

    for _ in range(10):
        await limiter.acquire()

    mock_monotonic[0] += 2.0
    await limiter.acquire()

    assert len(mock_sleep) <= 1


@pytest.mark.asyncio
async def test_parallel_acquire_serializes(
    mock_monotonic: list[float], mock_sleep: list[float]
) -> None:
    """Concurrent acquire calls wait in queue."""
    limiter = RateLimiter(capacity=3, refill_per_sec=10.0)

    tasks = [limiter.acquire() for _ in range(5)]

    results = await asyncio.gather(*tasks)

    assert len(results) == 5
    assert len(mock_sleep) >= 2
