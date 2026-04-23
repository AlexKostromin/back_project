from __future__ import annotations

import time
from collections import deque
from enum import Enum

from app.parsers.exceptions import CircuitOpenError


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit breaker with sliding window and cooldown period."""

    def __init__(
        self,
        window_size: int,
        failure_threshold: float,
        cooldown_sec: float,
    ) -> None:
        self._window_size = window_size
        self._failure_threshold = failure_threshold
        self._cooldown_sec = cooldown_sec
        self._state = CircuitState.CLOSED
        self._window: deque[bool] = deque(maxlen=window_size)
        self._opened_at: float | None = None

    def guard(self) -> None:
        """Check if circuit allows request; raises CircuitOpenError if open."""
        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._state = CircuitState.HALF_OPEN
            else:
                raise CircuitOpenError("Circuit breaker is open")

    def record_success(self) -> None:
        """Record successful request."""
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._window.clear()
            self._opened_at = None
        else:
            self._window.append(True)

    def record_failure(self) -> None:
        """Record failed request and potentially open circuit."""
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
        else:
            self._window.append(False)
            if self._is_threshold_exceeded():
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()

    def _should_attempt_reset(self) -> bool:
        if self._opened_at is None:
            return False
        return (time.monotonic() - self._opened_at) >= self._cooldown_sec

    def _is_threshold_exceeded(self) -> bool:
        if len(self._window) < self._window_size:
            return False
        failure_count = sum(1 for success in self._window if not success)
        return (failure_count / self._window_size) > self._failure_threshold
