from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import ClassVar

import pytest

from app.parsers.base import BaseParser
from app.parsers.schemas import (
    AppealStatus,
    CourtType,
    DisputeType,
    DocType,
    ParsedDecision,
    Participant,
    ParticipantRole,
    RawDocument,
    ResultType,
)


def test_cannot_instantiate_abstract_base():
    """BaseParser is abstract and cannot be instantiated directly."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        BaseParser()  # type: ignore


def test_subclass_without_abstract_methods_fails():
    """Subclass without implementing abstract methods cannot be instantiated."""

    class IncompleteParser(BaseParser):
        source_key: ClassVar[str] = "incomplete"

    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        IncompleteParser()  # type: ignore


@pytest.mark.asyncio
async def test_fetch_and_parse_calls_both_methods():
    """fetch_and_parse should call fetch_document and parse sequentially."""

    class TestParser(BaseParser):
        source_key: ClassVar[str] = "test"

        def __init__(self):
            self.fetch_called = False
            self.parse_called = False

        async def crawl(self, *, date_from=None, date_to=None, limit=None):
            yield  # pragma: no cover

        async def fetch_document(self, source_id: str) -> RawDocument:
            self.fetch_called = True
            return RawDocument(
                source_name=self.source_key,
                source_id=source_id,
                html='{"test": "data"}',
                url=None,
                crawled_at=datetime.now(),
            )

        async def parse(self, raw: RawDocument) -> ParsedDecision:
            assert self.fetch_called, "fetch_document should be called before parse"
            self.parse_called = True
            full_text = "Test text"
            text_hash = "a" * 64  # Valid 64-char hex
            return ParsedDecision(
                source_name=self.source_key,
                source_id=raw.source_id,
                case_number="TEST-001",
                court_name="Test Court",
                court_type=CourtType.ARBITRAZH,
                instance_level=1,
                decision_date=datetime.now().date(),
                doc_type=DocType.DECISION,
                judges=["Test Judge"],
                result=ResultType.SATISFIED,
                dispute_type=DisputeType.CIVIL,
                participants=[],
                full_text=full_text,
                text_hash=text_hash,
                source_url=raw.url or "https://example.com/test",
                crawled_at=raw.crawled_at,
                parsed_at=datetime.now(),
            )

    parser = TestParser()
    result = await parser.fetch_and_parse("test_id")

    assert parser.fetch_called
    assert parser.parse_called
    assert result.source_id == "test_id"


@pytest.mark.asyncio
async def test_health_check_default():
    """Default health_check should return True."""

    class MinimalParser(BaseParser):
        source_key: ClassVar[str] = "minimal"

        async def crawl(self, *, date_from=None, date_to=None, limit=None):
            yield  # pragma: no cover

        async def fetch_document(self, source_id: str) -> RawDocument:
            pass  # pragma: no cover

        async def parse(self, raw: RawDocument) -> ParsedDecision:
            pass  # pragma: no cover

    parser = MinimalParser()
    assert await parser.health_check() is True


@pytest.mark.asyncio
async def test_get_pdf_default():
    """Default get_pdf should return None."""

    class MinimalParser(BaseParser):
        source_key: ClassVar[str] = "minimal"

        async def crawl(self, *, date_from=None, date_to=None, limit=None):
            yield  # pragma: no cover

        async def fetch_document(self, source_id: str) -> RawDocument:
            pass  # pragma: no cover

        async def parse(self, raw: RawDocument) -> ParsedDecision:
            pass  # pragma: no cover

    parser = MinimalParser()
    assert await parser.get_pdf("test_id") is None


@pytest.mark.asyncio
async def test_health_check_override():
    """Subclass can override health_check."""

    class CustomParser(BaseParser):
        source_key: ClassVar[str] = "custom"

        def __init__(self, healthy: bool):
            self.healthy = healthy

        async def crawl(self, *, date_from=None, date_to=None, limit=None):
            yield  # pragma: no cover

        async def fetch_document(self, source_id: str) -> RawDocument:
            pass  # pragma: no cover

        async def parse(self, raw: RawDocument) -> ParsedDecision:
            pass  # pragma: no cover

        async def health_check(self) -> bool:
            return self.healthy

    healthy_parser = CustomParser(healthy=True)
    assert await healthy_parser.health_check() is True

    unhealthy_parser = CustomParser(healthy=False)
    assert await unhealthy_parser.health_check() is False


@pytest.mark.asyncio
async def test_get_pdf_override():
    """Subclass can override get_pdf."""

    class PdfParser(BaseParser):
        source_key: ClassVar[str] = "pdf"

        async def crawl(self, *, date_from=None, date_to=None, limit=None):
            yield  # pragma: no cover

        async def fetch_document(self, source_id: str) -> RawDocument:
            pass  # pragma: no cover

        async def parse(self, raw: RawDocument) -> ParsedDecision:
            pass  # pragma: no cover

        async def get_pdf(self, source_id: str) -> bytes | None:
            if source_id == "exists":
                return b"PDF content"
            return None

    parser = PdfParser()
    assert await parser.get_pdf("exists") == b"PDF content"
    assert await parser.get_pdf("missing") is None


@pytest.mark.asyncio
async def test_fetch_and_parse_logs_hashed_source_id(monkeypatch):
    """source_id in structlog calls must be a short hash, never the raw value."""
    from app.parsers import base as base_module

    captured: list[dict] = []

    def fake_info(event: str, **kwargs):
        captured.append({"event": event, **kwargs})

    monkeypatch.setattr(base_module.logger, "info", fake_info)

    class TraceParser(BaseParser):
        source_key: ClassVar[str] = "trace"

        async def crawl(self, *, date_from=None, date_to=None, limit=None):
            yield  # pragma: no cover

        async def fetch_document(self, source_id: str) -> RawDocument:
            return RawDocument(
                source_name=self.source_key,
                source_id=source_id,
                html='{"x": 1}',
                url=None,
                crawled_at=datetime.now(),
            )

        async def parse(self, raw: RawDocument) -> ParsedDecision:
            return ParsedDecision(
                source_name=self.source_key,
                source_id=raw.source_id,
                case_number="X",
                court_name="X",
                court_type=CourtType.ARBITRAZH,
                instance_level=1,
                decision_date=datetime.now().date(),
                doc_type=DocType.DECISION,
                judges=[],
                result=ResultType.OTHER,
                dispute_type=DisputeType.CIVIL,
                participants=[],
                full_text="x",
                text_hash="a" * 64,
                source_url="https://example.com/x",
                crawled_at=raw.crawled_at,
                parsed_at=datetime.now(),
            )

    raw_id = "ИНН7701234567"
    await TraceParser().fetch_and_parse(raw_id)

    assert len(captured) == 2
    for entry in captured:
        logged = entry["source_id"]
        assert logged != raw_id, "raw source_id leaked into log"
        assert len(logged) == 8 and all(c in "0123456789abcdef" for c in logged)
