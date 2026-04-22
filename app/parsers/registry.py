from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.parsers.base import BaseParser


class ParserRegistry:
    """In-memory registry for parser classes."""

    def __init__(self) -> None:
        self._parsers: dict[str, type[BaseParser]] = {}

    def register(self, parser_cls: type[BaseParser]) -> None:
        """Register a parser class by its source_key."""
        source_key = parser_cls.source_key

        if not source_key or not source_key.strip():
            raise ValueError("Parser source_key cannot be empty")

        if source_key in self._parsers:
            raise ValueError(f"Parser with source_key '{source_key}' already registered")

        self._parsers[source_key] = parser_cls

    def get(self, source_key: str) -> type[BaseParser]:
        """Get parser class by source_key."""
        if source_key not in self._parsers:
            raise KeyError(f"No parser registered for source_key '{source_key}'")

        return self._parsers[source_key]

    def available(self) -> list[str]:
        """List all registered source keys."""
        return list(self._parsers.keys())


parser_registry = ParserRegistry()
