from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.parsers.exceptions import ParseError, SourceUnavailableError
from app.parsers.file_parser import FileParser
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


@pytest.mark.asyncio
async def test_fetch_document_valid(tmp_fixtures_dir: Path):
    """fetch_document should return RawDocument with correct fields."""
    parser = FileParser(tmp_fixtures_dir)
    raw = await parser.fetch_document("case_001")

    assert isinstance(raw, RawDocument)
    assert raw.source_name == "file"
    assert raw.source_id == "case_001"
    assert raw.url is None
    assert raw.html is not None
    assert raw.html != ""
    assert raw.pdf_bytes is None
    assert isinstance(raw.crawled_at, datetime)
    assert "А40-12345/2025" in raw.html


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
    assert parsed.source_name == "file"
    assert parsed.source_id == "case_001"
    assert parsed.case_number == "А40-12345/2025"
    assert parsed.court_name == "Арбитражный суд города Москвы"
    assert parsed.court_type == CourtType.ARBITRAZH
    assert parsed.instance_level == 1
    assert parsed.region == "г. Москва"
    assert parsed.decision_date == date(2025, 3, 15)
    assert parsed.publication_date == date(2025, 3, 20)
    assert parsed.doc_type == DocType.DECISION
    assert parsed.judges == ["Иванов И.И."]
    assert parsed.result == ResultType.SATISFIED
    assert parsed.appeal_status == AppealStatus.NONE
    assert parsed.category == "Взыскание задолженности"
    assert parsed.dispute_type == DisputeType.CIVIL
    assert parsed.claim_amount == Decimal("15000000.00")
    assert len(parsed.participants) == 2
    assert parsed.participants[0].name == "ООО Ромашка"
    assert parsed.participants[0].role == ParticipantRole.PLAINTIFF
    assert parsed.participants[1].name == "АО Василёк"
    assert parsed.participants[1].role == ParticipantRole.DEFENDANT
    assert len(parsed.norms) == 1
    assert parsed.norms[0].law_name == "ГК РФ"
    assert parsed.norms[0].article == "10"
    assert "Решение суда" in parsed.full_text
    assert len(parsed.text_hash) == 64
    assert parsed.sections.get("resolutive") == "Удовлетворить исковые требования..."
    assert parsed.source_url.startswith("file://")
    assert isinstance(parsed.crawled_at, datetime)
    assert isinstance(parsed.parsed_at, datetime)


@pytest.mark.asyncio
async def test_crawl_all(tmp_fixtures_dir: Path):
    """crawl should iterate all JSON files in directory."""
    parser = FileParser(tmp_fixtures_dir)
    results = []

    async for raw in parser.crawl():
        results.append(raw)

    # 6 fixtures: case_001, case_002, invalid_enum_value, invalid_json, invalid_missing_field, invalid_wrong_type
    assert len(results) == 6
    assert all(isinstance(r, RawDocument) for r in results)
    assert all(r.source_name == "file" for r in results)


@pytest.mark.asyncio
async def test_crawl_with_limit(tmp_fixtures_dir: Path):
    """crawl with limit=1 should return only one item."""
    parser = FileParser(tmp_fixtures_dir)
    results = []

    async for raw in parser.crawl(limit=1):
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
async def test_parse_invalid_enum_value(tmp_fixtures_dir: Path):
    """parse with JSON having invalid enum value should raise ParseError."""
    parser = FileParser(tmp_fixtures_dir)
    raw = await parser.fetch_document("invalid_enum_value")

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
        source_name="file",
        source_id="test",
        case_number="TEST-001",
        court_name="Test Court",
        court_type=CourtType.ARBITRAZH,
        instance_level=1,
        decision_date=date(2025, 1, 1),
        doc_type=DocType.DECISION,
        judges=["Judge"],
        result=ResultType.SATISFIED,
        dispute_type=DisputeType.CIVIL,
        participants=[],
        full_text="Test",
        text_hash="a" * 64,
        source_url="https://example.com/test",
        crawled_at=datetime.now(),
        parsed_at=datetime.now(),
    )

    with pytest.raises(ValidationError, match="frozen"):
        parsed.case_number = "MODIFIED"  # type: ignore


def test_raw_document_is_frozen():
    """RawDocument should be frozen (immutable)."""
    raw = RawDocument(
        source_name="file",
        source_id="test",
        html="content",
        url=None,
        crawled_at=datetime.now(),
    )

    with pytest.raises(ValidationError, match="frozen"):
        raw.source_id = "modified"  # type: ignore


def test_raw_document_invariant_no_content():
    """RawDocument without html or pdf_bytes should raise ValueError."""
    with pytest.raises(ValueError, match="At least one of"):
        RawDocument(
            source_name="file",
            source_id="test",
            html=None,
            pdf_bytes=None,
            url=None,
            crawled_at=datetime.now(),
        )


@pytest.mark.asyncio
async def test_text_hash_computation(tmp_fixtures_dir: Path):
    """text_hash should be computed correctly from full_text."""
    parser = FileParser(tmp_fixtures_dir)
    parsed = await parser.fetch_and_parse("case_001")

    expected_hash = sha256(parsed.full_text.encode("utf-8")).hexdigest()
    assert parsed.text_hash == expected_hash
    assert len(parsed.text_hash) == 64
    assert all(c in "0123456789abcdef" for c in parsed.text_hash)


@pytest.mark.asyncio
async def test_parse_rejects_oversized_json(tmp_fixtures_dir: Path):
    """parse should reject JSON larger than MAX_JSON_SIZE_BYTES."""
    from datetime import datetime, timezone
    from app.parsers.schemas import RawDocument

    parser = FileParser(tmp_fixtures_dir)

    # Create a RawDocument with >10MB of content
    large_content = "x" * (11 * 1024 * 1024)  # 11 MB
    raw = RawDocument(
        source_name="file",
        source_id="oversized_doc",
        html=large_content,
        url=None,
        crawled_at=datetime.now(timezone.utc),
    )

    with pytest.raises(ParseError, match="Document too large"):
        await parser.parse(raw)


def test_validate_path_rejects_null_byte(tmp_fixtures_dir: Path):
    """_validate_path should reject filenames containing null bytes."""
    parser = FileParser(tmp_fixtures_dir)

    with pytest.raises(ValueError, match="Null byte in filename"):
        parser._validate_path("file\x00.json")


@pytest.mark.parametrize("filename", [
    "CON.json",
    "NUL.json",
    "COM1.json",
    "LPT9.json",
    "con.json",
    "Con.JSON",
    "prn.json",
    "aux.json",
])
def test_validate_path_rejects_windows_reserved_name(tmp_fixtures_dir: Path, filename: str):
    """_validate_path should reject Windows reserved names."""
    parser = FileParser(tmp_fixtures_dir)

    with pytest.raises(ValueError, match="Reserved Windows filename"):
        parser._validate_path(filename)


@pytest.mark.asyncio
async def test_parse_validation_error_message_is_generic(tmp_fixtures_dir: Path):
    """ParseError message should not leak field-level validation details."""
    parser = FileParser(tmp_fixtures_dir)
    raw = await parser.fetch_document("invalid_missing_field")

    with pytest.raises(ParseError) as exc_info:
        await parser.parse(raw)

    error_message = str(exc_info.value)
    # Should not contain specific field names from the validation error
    assert "source_url" not in error_message.lower()
    assert "field required" not in error_message.lower()
    # Should be generic
    assert "Failed to parse document" in error_message


@pytest.mark.asyncio
async def test_parse_json_decode_error_message_is_generic(tmp_fixtures_dir: Path):
    """ParseError for JSON decode errors should not leak JSON parsing details."""
    parser = FileParser(tmp_fixtures_dir)
    raw = await parser.fetch_document("invalid_json")

    with pytest.raises(ParseError) as exc_info:
        await parser.parse(raw)

    error_message = str(exc_info.value)
    # Should be generic, not contain JSON parser details in the exception message
    assert "Failed to parse document" in error_message
    # The original error details should be in __cause__, not in the message itself
    assert exc_info.value.__cause__ is not None
