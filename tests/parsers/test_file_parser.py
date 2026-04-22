from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.parsers.exceptions import ParseError, SourceUnavailableError
from app.parsers.file_parser import FileParser
from app.parsers.schemas import ParsedDecision, RawDecision


@pytest.mark.asyncio
async def test_fetch_document_valid(tmp_fixtures_dir: Path):
    """fetch_document should return RawDecision with correct fields."""
    parser = FileParser(tmp_fixtures_dir)
    raw = await parser.fetch_document("case_001")

    assert isinstance(raw, RawDecision)
    assert raw.source == "file"
    assert raw.source_id == "case_001"
    assert raw.url is None
    assert raw.raw_content != ""
    assert isinstance(raw.fetched_at, datetime)
    assert "А40-12345/2025" in raw.raw_content


@pytest.mark.asyncio
async def test_fetch_document_nonexistent(tmp_fixtures_dir: Path):
    """fetch_document with nonexistent source_id should raise SourceUnavailableError."""
    parser = FileParser(tmp_fixtures_dir)

    with pytest.raises(SourceUnavailableError, match="Document not found"):
        await parser.fetch_document("nonexistent")


@pytest.mark.asyncio
async def test_fetch_and_parse_valid(tmp_fixtures_dir: Path):
    """fetch_and_parse should return ParsedDecision with all fields from fixture."""
    parser = FileParser(tmp_fixtures_dir)
    parsed = await parser.fetch_and_parse("case_001")

    assert isinstance(parsed, ParsedDecision)
    assert parsed.source == "file"
    assert parsed.source_id == "case_001"
    assert parsed.case_number == "А40-12345/2025"
    assert parsed.court_name == "Арбитражный суд города Москвы"
    assert parsed.judges == ["Иванов И.И."]
    assert parsed.decision_date == date(2025, 3, 15)
    assert parsed.category == "Взыскание задолженности"
    assert parsed.result == "Удовлетворено"
    assert parsed.appeal_status is None
    assert parsed.participants == ["ООО Ромашка", "АО Василёк"]
    assert "Решение суда" in parsed.full_text
    assert parsed.url is None
    assert isinstance(parsed.fetched_at, datetime)
    assert isinstance(parsed.parsed_at, datetime)


@pytest.mark.asyncio
async def test_fetch_list_all(tmp_fixtures_dir: Path):
    """fetch_list should iterate all JSON files in directory."""
    parser = FileParser(tmp_fixtures_dir)
    results = []

    async for raw in parser.fetch_list():
        results.append(raw)

    # 5 fixtures: case_001, case_002, invalid_json, invalid_missing_field, invalid_wrong_type
    assert len(results) == 5
    assert all(isinstance(r, RawDecision) for r in results)
    assert all(r.source == "file" for r in results)


@pytest.mark.asyncio
async def test_fetch_list_with_limit(tmp_fixtures_dir: Path):
    """fetch_list with limit=1 should return only one item."""
    parser = FileParser(tmp_fixtures_dir)
    results = []

    async for raw in parser.fetch_list(limit=1):
        results.append(raw)

    assert len(results) == 1


@pytest.mark.asyncio
async def test_parse_invalid_json(tmp_fixtures_dir: Path):
    """parse with invalid JSON should raise ParseError."""
    parser = FileParser(tmp_fixtures_dir)
    raw = await parser.fetch_document("invalid_json")

    with pytest.raises(ParseError, match="Failed to parse"):
        await parser.parse(raw)


@pytest.mark.asyncio
async def test_parse_missing_required_field(tmp_fixtures_dir: Path):
    """parse with JSON missing required field should raise ParseError."""
    parser = FileParser(tmp_fixtures_dir)
    raw = await parser.fetch_document("invalid_missing_field")

    with pytest.raises(ParseError, match="Failed to parse"):
        await parser.parse(raw)


@pytest.mark.asyncio
async def test_parse_invalid_field_type(tmp_fixtures_dir: Path):
    """parse with JSON having invalid field type should raise ParseError."""
    parser = FileParser(tmp_fixtures_dir)
    raw = await parser.fetch_document("invalid_wrong_type")

    with pytest.raises(ParseError, match="Failed to parse"):
        await parser.parse(raw)


@pytest.mark.asyncio
async def test_path_traversal_protection(tmp_fixtures_dir: Path):
    """fetch_document with path traversal attempt should raise ValueError."""
    parser = FileParser(tmp_fixtures_dir)

    with pytest.raises(ValueError, match="Path traversal detected"):
        await parser.fetch_document("../../../etc/passwd")


@pytest.mark.asyncio
async def test_path_traversal_absolute_path(tmp_fixtures_dir: Path):
    """fetch_document with absolute path should raise ValueError."""
    parser = FileParser(tmp_fixtures_dir)

    with pytest.raises(ValueError, match="Path traversal detected"):
        await parser.fetch_document("/etc/passwd")


def test_constructor_with_nonexistent_directory(tmp_path: Path):
    """FileParser constructor with nonexistent directory should raise ValueError."""
    nonexistent = tmp_path / "does_not_exist"

    with pytest.raises(ValueError, match="does not exist"):
        FileParser(nonexistent)


def test_parsed_decision_is_frozen(tmp_fixtures_dir: Path):
    """ParsedDecision should be frozen (immutable)."""
    from datetime import date, datetime

    parsed = ParsedDecision(
        source="file",
        source_id="test",
        case_number="TEST-001",
        court_name="Test Court",
        judges=["Judge"],
        decision_date=date(2025, 1, 1),
        category=None,
        result=None,
        appeal_status=None,
        participants=[],
        full_text="Test",
        url=None,
        fetched_at=datetime.now(),
        parsed_at=datetime.now(),
    )

    with pytest.raises(ValidationError, match="frozen"):
        parsed.case_number = "MODIFIED"  # type: ignore


def test_raw_decision_is_frozen():
    """RawDecision should be frozen (immutable)."""
    raw = RawDecision(
        source="file",
        source_id="test",
        url=None,
        raw_content="content",
        fetched_at=datetime.now(),
    )

    with pytest.raises(ValidationError, match="frozen"):
        raw.source_id = "modified"  # type: ignore
