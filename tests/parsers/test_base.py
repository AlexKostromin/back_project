from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import pytest

from app.parsers.base import BaseParser
from app.parsers.schemas import ParsedDecision, RawDecision


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

        async def fetch_list(self, *, since=None, limit=100):
            yield  # pragma: no cover

        async def fetch_document(self, source_id: str) -> RawDecision:
            self.fetch_called = True
            return RawDecision(
                source=self.source_key,
                source_id=source_id,
                url=None,
                raw_content='{"test": "data"}',
                fetched_at=datetime.now(),
            )

        async def parse(self, raw: RawDecision) -> ParsedDecision:
            assert self.fetch_called, "fetch_document should be called before parse"
            self.parse_called = True
            return ParsedDecision(
                source=raw.source,
                source_id=raw.source_id,
                case_number="TEST-001",
                court_name="Test Court",
                judges=["Test Judge"],
                decision_date=datetime.now().date(),
                category=None,
                result=None,
                appeal_status=None,
                participants=[],
                full_text="Test text",
                url=raw.url,
                fetched_at=raw.fetched_at,
                parsed_at=datetime.now(),
            )

    parser = TestParser()
    result = await parser.fetch_and_parse("test_id")

    assert parser.fetch_called
    assert parser.parse_called
    assert result.source_id == "test_id"
