from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.parsers.kad.chronology import build_pdf_url, parse_chronology_response


@pytest.fixture
def fixture_response() -> dict:
    """Load CaseDocumentsPage fixture response."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "kad_documents_response.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_parse_chronology_response_extracts_all_documents(fixture_response: dict) -> None:
    """Parse chronology response should extract all valid documents."""
    refs = parse_chronology_response(fixture_response)

    assert len(refs) == 3

    # All documents have IsAct=true and IsDeleted=false in fixture
    assert all(ref.document_id for ref in refs)
    assert all(ref.document_date for ref in refs)
    assert all(ref.url for ref in refs)


def test_parse_chronology_response_builds_correct_urls(fixture_response: dict) -> None:
    """Parse chronology response should build correct PDF URLs."""
    refs = parse_chronology_response(fixture_response)

    # All documents in fixture have IsSimpleJustice=false
    for ref in refs:
        assert ref.url is not None
        assert ref.url.startswith("https://kad.arbitr.ru/Kad/PdfDocument/")
        assert "00000000-0000-0000-0000-00000000ca5e" in ref.url  # case_id from fixture


def test_parse_chronology_response_extracts_correct_dates(fixture_response: dict) -> None:
    """Parse chronology response should extract correct document dates in MSK."""
    refs = parse_chronology_response(fixture_response)

    # Extract dates from fixture "Date" field (not DisplayDate)
    # /Date(1772088840000)/ = 2026-02-26 00:01:40 UTC = 2026-02-26 03:01:40 MSK
    # /Date(1719293331000)/ = 2024-06-25 08:28:51 UTC = 2024-06-25 11:28:51 MSK
    # /Date(1701684958000)/ = 2023-12-04 00:15:58 UTC = 2023-12-04 03:15:58 MSK

    expected_dates = {
        date(2026, 2, 26),
        date(2024, 6, 25),
        date(2023, 12, 4),
    }

    actual_dates = {ref.document_date for ref in refs}
    assert actual_dates == expected_dates


def test_parse_chronology_response_extracts_document_types(fixture_response: dict) -> None:
    """Parse chronology response should extract DocumentTypeName."""
    refs = parse_chronology_response(fixture_response)

    document_types = {ref.document_type for ref in refs}
    assert "Определение" in document_types
    assert "Решения и постановления" in document_types


def test_parse_chronology_response_extracts_descriptions(fixture_response: dict) -> None:
    """Parse chronology response should extract ContentTypes[0] as description."""
    refs = parse_chronology_response(fixture_response)

    # Find doc with Id ending in d1
    ref_d1 = next(
        ref for ref in refs if ref.document_id == "00000000-0000-0000-0000-0000000000d1"
    )
    assert ref_d1.description == "Определение арбитражного суда"

    # Find doc with Id ending in d2
    ref_d2 = next(
        ref for ref in refs if ref.document_id == "00000000-0000-0000-0000-0000000000d2"
    )
    assert (
        ref_d2.description
        == "Резолютивная часть решения суда по делу, рассматриваемому в порядке упрощенного производства"
    )


def test_parse_chronology_response_filters_non_acts() -> None:
    """Parse chronology response should filter out documents with IsAct=false."""
    payload = {
        "Success": True,
        "Result": {
            "Items": [
                {
                    "Id": "test-id-1",
                    "CaseId": "case-1",
                    "Date": "/Date(1609459200000)/",
                    "FileName": "test.pdf",
                    "IsAct": False,
                    "IsDeleted": False,
                    "DocumentTypeName": "Заявление",
                },
            ],
        },
    }

    refs = parse_chronology_response(payload)
    assert len(refs) == 0


def test_parse_chronology_response_filters_deleted_documents() -> None:
    """Parse chronology response should filter out documents with IsDeleted=true."""
    payload = {
        "Success": True,
        "Result": {
            "Items": [
                {
                    "Id": "test-id-1",
                    "CaseId": "case-1",
                    "Date": "/Date(1609459200000)/",
                    "FileName": "test.pdf",
                    "IsAct": True,
                    "IsDeleted": True,
                    "DocumentTypeName": "Определение",
                },
            ],
        },
    }

    refs = parse_chronology_response(payload)
    assert len(refs) == 0


def test_parse_chronology_response_handles_empty_items() -> None:
    """Parse chronology response should handle empty Items list without error."""
    payload = {
        "Success": True,
        "Result": {
            "Items": [],
        },
    }

    refs = parse_chronology_response(payload)
    assert refs == []


def test_parse_chronology_response_raises_on_invalid_success() -> None:
    """Parse chronology response should raise ValueError if Success != True."""
    payload = {
        "Success": False,
        "Message": "Error occurred",
    }

    with pytest.raises(ValueError) as exc_info:
        parse_chronology_response(payload)

    assert "Success != True" in str(exc_info.value)


def test_parse_chronology_response_raises_on_missing_result() -> None:
    """Parse chronology response should raise ValueError if Result is missing."""
    payload = {
        "Success": True,
    }

    with pytest.raises(ValueError) as exc_info:
        parse_chronology_response(payload)

    assert "missing Result.Items" in str(exc_info.value)


def test_parse_chronology_response_raises_on_missing_items() -> None:
    """Parse chronology response should raise ValueError if Items is missing."""
    payload = {
        "Success": True,
        "Result": {},
    }

    with pytest.raises(ValueError) as exc_info:
        parse_chronology_response(payload)

    assert "missing Result.Items" in str(exc_info.value)


def test_build_pdf_url_kad_prefix() -> None:
    """Build PDF URL should use Kad prefix when is_simple_justice=False."""
    url = build_pdf_url(
        case_id="00000000-0000-0000-0000-000000000001",
        document_id="00000000-0000-0000-0000-000000000002",
        file_name="test.pdf",
        is_simple_justice=False,
    )

    assert url == "https://kad.arbitr.ru/Kad/PdfDocument/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000002/test.pdf"


def test_build_pdf_url_simple_justice_prefix() -> None:
    """Build PDF URL should use SimpleJustice prefix when is_simple_justice=True."""
    url = build_pdf_url(
        case_id="00000000-0000-0000-0000-000000000001",
        document_id="00000000-0000-0000-0000-000000000002",
        file_name="test.pdf",
        is_simple_justice=True,
    )

    assert url == "https://kad.arbitr.ru/SimpleJustice/PdfDocument/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000002/test.pdf"


def test_build_pdf_url_raises_on_empty_case_id() -> None:
    """Build PDF URL should raise ValueError if case_id is empty."""
    with pytest.raises(ValueError) as exc_info:
        build_pdf_url(
            case_id="",
            document_id="00000000-0000-0000-0000-000000000001",
            file_name="test.pdf",
            is_simple_justice=False,
        )

    assert "case_id cannot be empty" in str(exc_info.value)


def test_build_pdf_url_raises_on_empty_document_id() -> None:
    """Build PDF URL should raise ValueError if document_id is empty."""
    with pytest.raises(ValueError) as exc_info:
        build_pdf_url(
            case_id="00000000-0000-0000-0000-000000000001",
            document_id="",
            file_name="test.pdf",
            is_simple_justice=False,
        )

    assert "document_id cannot be empty" in str(exc_info.value)


def test_build_pdf_url_raises_on_empty_file_name() -> None:
    """Build PDF URL should raise ValueError if file_name is empty."""
    with pytest.raises(ValueError) as exc_info:
        build_pdf_url(
            case_id="00000000-0000-0000-0000-000000000001",
            document_id="00000000-0000-0000-0000-000000000002",
            file_name="",
            is_simple_justice=False,
        )

    assert "file_name cannot be empty" in str(exc_info.value)


class TestBuildPdfUrlValidation:
    """Security validations on build_pdf_url against URL injection."""

    @pytest.mark.parametrize(
        "case_id",
        [
            "../../etc/passwd",
            "not-a-uuid",
            "abc",
            "12345678-1234-1234-1234-12345678901",  # 35 chars, missing 1
        ],
    )
    def test_rejects_invalid_case_id(self, case_id: str) -> None:
        with pytest.raises(ValueError, match="case_id"):
            build_pdf_url(
                case_id=case_id,
                document_id="00000000-0000-0000-0000-000000000001",
                file_name="test.pdf",
                is_simple_justice=False,
            )

    @pytest.mark.parametrize(
        "document_id",
        ["../bad", "not-uuid"],
    )
    def test_rejects_invalid_document_id(self, document_id: str) -> None:
        with pytest.raises(ValueError, match="document_id"):
            build_pdf_url(
                case_id="00000000-0000-0000-0000-000000000001",
                document_id=document_id,
                file_name="test.pdf",
                is_simple_justice=False,
            )

    @pytest.mark.parametrize(
        "file_name,fragment",
        [
            ("a/b.pdf", "path separators"),
            ("a\\b.pdf", "path separators"),
            ("..test.pdf", "'\\.\\.'"),
            ("test..pdf", "'\\.\\.'"),
            ("test.pdf?admin=1", "query/fragment"),
            ("test.pdf#section", "query/fragment"),
            ("test.exe", "must end with .pdf"),
            ("a" * 300 + ".pdf", "too long"),
        ],
    )
    def test_rejects_unsafe_file_name(self, file_name: str, fragment: str) -> None:
        with pytest.raises(ValueError, match=fragment):
            build_pdf_url(
                case_id="00000000-0000-0000-0000-000000000001",
                document_id="00000000-0000-0000-0000-000000000002",
                file_name=file_name,
                is_simple_justice=False,
            )

    def test_real_kad_filename_passes(self) -> None:
        url = build_pdf_url(
            case_id="00000000-0000-0000-0000-000000000001",
            document_id="00000000-0000-0000-0000-000000000002",
            file_name="A00-00001-2023_20260226_Opredelenie.pdf",
            is_simple_justice=False,
        )
        assert url.endswith("A00-00001-2023_20260226_Opredelenie.pdf")


def test_parse_chronology_rejects_huge_items_list() -> None:
    """Parse chronology response should reject response with too many items."""
    payload = {
        "Success": True,
        "Result": {"Items": [{} for _ in range(1001)]},
    }
    with pytest.raises(ValueError, match="Too many items"):
        parse_chronology_response(payload)
