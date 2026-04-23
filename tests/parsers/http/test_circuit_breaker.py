from __future__ import annotations

import time

import pytest

from app.parsers.exceptions import CircuitOpenError
from app.parsers.http.circuit_breaker import CircuitBreaker, CircuitState


@pytest.fixture
def mock_monotonic(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Mock time.monotonic to control time in tests."""
    current_time = [0.0]

    def mock_time() -> float:
        return current_time[0]

    monkeypatch.setattr("app.parsers.http.circuit_breaker.time.monotonic", mock_time)
    return current_time


@pytest.mark.asyncio
async def test_guard_passes_when_closed() -> None:
    """Guard allows requests when circuit is closed."""
    breaker = CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0)

    breaker.guard()


@pytest.mark.asyncio
async def test_circuit_stays_closed_below_threshold() -> None:
    """Circuit remains closed when failure rate is below threshold."""
    breaker = CircuitBreaker(window_size=10, failure_threshold=0.3, cooldown_sec=60.0)

    for _ in range(7):
        breaker.record_success()
    for _ in range(3):
        breaker.record_failure()

    breaker.guard()


@pytest.mark.asyncio
async def test_circuit_opens_when_threshold_exceeded() -> None:
    """Circuit opens when failure rate exceeds threshold."""
    breaker = CircuitBreaker(window_size=10, failure_threshold=0.3, cooldown_sec=60.0)

    for _ in range(6):
        breaker.record_success()
    for _ in range(4):
        breaker.record_failure()

    with pytest.raises(CircuitOpenError):
        breaker.guard()


@pytest.mark.asyncio
async def test_circuit_half_open_after_cooldown(mock_monotonic: list[float]) -> None:
    """Circuit transitions to half-open after cooldown period."""
    breaker = CircuitBreaker(window_size=10, failure_threshold=0.3, cooldown_sec=60.0)

    for _ in range(6):
        breaker.record_success()
    for _ in range(4):
        breaker.record_failure()

    with pytest.raises(CircuitOpenError):
        breaker.guard()

    mock_monotonic[0] = 60.0
    breaker.guard()

    assert breaker._state == CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_half_open_success_closes_circuit(mock_monotonic: list[float]) -> None:
    """Successful request in half-open state closes circuit."""
    breaker = CircuitBreaker(window_size=10, failure_threshold=0.3, cooldown_sec=60.0)

    for _ in range(6):
        breaker.record_success()
    for _ in range(4):
        breaker.record_failure()

    mock_monotonic[0] = 60.0
    breaker.guard()
    breaker.record_success()

    assert breaker._state == CircuitState.CLOSED
    breaker.guard()


@pytest.mark.asyncio
async def test_half_open_failure_reopens_circuit(mock_monotonic: list[float]) -> None:
    """Failed request in half-open state reopens circuit."""
    breaker = CircuitBreaker(window_size=10, failure_threshold=0.3, cooldown_sec=60.0)

    for _ in range(6):
        breaker.record_success()
    for _ in range(4):
        breaker.record_failure()

    mock_monotonic[0] = 60.0
    breaker.guard()
    breaker.record_failure()

    assert breaker._state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.guard()


@pytest.mark.asyncio
async def test_window_slides_correctly() -> None:
    """Sliding window correctly maintains only recent results."""
    breaker = CircuitBreaker(window_size=5, failure_threshold=0.4, cooldown_sec=60.0)

    for _ in range(3):
        breaker.record_failure()
    for _ in range(2):
        breaker.record_success()

    breaker.record_success()
    breaker.record_success()
    breaker.record_success()

    breaker.guard()
