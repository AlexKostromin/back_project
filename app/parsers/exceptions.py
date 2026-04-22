from __future__ import annotations


class ParserError(Exception):
    """Base exception for parser subsystem."""

    pass


class SourceUnavailableError(ParserError):
    """Source is unavailable or unreachable."""

    pass


class RateLimitError(ParserError):
    """Rate limit exceeded."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ParseError(ParserError):
    """Failed to parse a specific document."""

    pass


class CircuitOpenError(ParserError):
    """Circuit breaker is open after consecutive errors."""

    pass


class MaxRetriesError(ParserError):
    """Maximum retry attempts exceeded."""

    def __init__(self, message: str, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts
