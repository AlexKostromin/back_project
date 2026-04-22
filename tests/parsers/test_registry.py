from __future__ import annotations

from typing import ClassVar

import pytest

from app.parsers.base import BaseParser
from app.parsers.registry import ParserRegistry


class DummyParser(BaseParser):
    """Minimal concrete parser for testing."""

    source_key: ClassVar[str] = "dummy"

    async def fetch_list(self, *, since=None, limit=100):
        yield  # pragma: no cover

    async def fetch_document(self, source_id: str):
        pass  # pragma: no cover

    async def parse(self, raw):
        pass  # pragma: no cover


class EmptyKeyParser(BaseParser):
    """Parser with empty source_key."""

    source_key: ClassVar[str] = ""

    async def fetch_list(self, *, since=None, limit=100):
        yield  # pragma: no cover

    async def fetch_document(self, source_id: str):
        pass  # pragma: no cover

    async def parse(self, raw):
        pass  # pragma: no cover


def test_register_parser():
    """Registering a parser should add it to available list."""
    registry = ParserRegistry()
    registry.register(DummyParser)

    assert "dummy" in registry.available()


def test_register_duplicate_source_key():
    """Registering the same source_key twice should raise ValueError."""
    registry = ParserRegistry()
    registry.register(DummyParser)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(DummyParser)


def test_register_empty_source_key():
    """Registering a parser with empty source_key should raise ValueError."""
    registry = ParserRegistry()

    with pytest.raises(ValueError, match="cannot be empty"):
        registry.register(EmptyKeyParser)


def test_get_registered_parser():
    """Getting a registered parser should return the class."""
    registry = ParserRegistry()
    registry.register(DummyParser)

    parser_cls = registry.get("dummy")
    assert parser_cls is DummyParser


def test_get_unknown_parser():
    """Getting an unknown source_key should raise KeyError."""
    registry = ParserRegistry()

    with pytest.raises(KeyError, match="No parser registered"):
        registry.get("unknown")


def test_file_parser_auto_registered():
    """FileParser should be auto-registered via module import."""
    # Import triggers registration side-effect in file_parser.py
    from app.parsers import parser_registry

    assert "file" in parser_registry.available()
    file_parser_cls = parser_registry.get("file")
    assert file_parser_cls.__name__ == "FileParser"


def test_available_returns_empty_list_initially():
    """A new registry should have no parsers."""
    registry = ParserRegistry()
    assert registry.available() == []


def test_available_returns_all_keys():
    """available() should return all registered source_keys."""
    registry = ParserRegistry()

    class ParserA(BaseParser):
        source_key: ClassVar[str] = "source_a"

        async def fetch_list(self, *, since=None, limit=100):
            yield  # pragma: no cover

        async def fetch_document(self, source_id: str):
            pass  # pragma: no cover

        async def parse(self, raw):
            pass  # pragma: no cover

    class ParserB(BaseParser):
        source_key: ClassVar[str] = "source_b"

        async def fetch_list(self, *, since=None, limit=100):
            yield  # pragma: no cover

        async def fetch_document(self, source_id: str):
            pass  # pragma: no cover

        async def parse(self, raw):
            pass  # pragma: no cover

    registry.register(ParserA)
    registry.register(ParserB)

    assert sorted(registry.available()) == ["source_a", "source_b"]


