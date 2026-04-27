from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.parsers.http import CircuitBreaker, RateLimiter, ResilientHttpClient, RetryPolicy
from app.parsers.kad.parser import KadArbitrParser
from app.parsers.registry import parser_registry
from app.parsers.schemas import CourtType, ParticipantRole


@pytest.fixture
def fixture_path() -> Path:
    """Return path to test fixture."""
    return Path(__file__).parent.parent / "fixtures" / "card_30f36558.html"


@pytest.fixture
def fixture_html(fixture_path: Path) -> str:
    """Load test fixture HTML."""
    return fixture_path.read_text(encoding="utf-8")


@pytest.fixture
def minimal_html() -> str:
    """Minimal HTML with only required fields."""
    return """
    <html>
        <body>
            <input type="hidden" id="caseId" value="test-case-id-123" />
            <input type="hidden" id="caseName" value="А00-0000/2026" />
            <span class="js-case-header-case_num" data-instance_level="1"></span>
            <div id="gr_case_judges">
                <a href="http://test.arbitr.ru/">Тестовый АС</a>
            </div>
        </body>
    </html>
    """


def test_parser_registered() -> None:
    """Parser should be registered in registry after import."""
    from app.parsers.kad import parser  # noqa: F401

    assert "arbitr" in parser_registry.available()


def test_parse_card_extracts_case_metadata(fixture_html: str) -> None:
    """Parse card should extract basic case metadata."""
    parser = KadArbitrParser()
    summary = parser.parse_card(
        fixture_html,
        case_id="30f36558-ebdf-42d4-b576-436abc20b478",
        source_url="https://kad.arbitr.ru/Card/30f36558-ebdf-42d4-b576-436abc20b478",
    )

    assert summary.case_id == "30f36558-ebdf-42d4-b576-436abc20b478"
    assert summary.case_number == "А37-1073/2026"
    assert summary.court_name == "АС Магаданской области"
    assert summary.court_type == CourtType.ARBITRAZH
    assert summary.instance_level == 1
    assert summary.dispute_category is not None
    assert "несостоятельности" in summary.dispute_category or "банкротстве" in summary.dispute_category


def test_parse_card_extracts_parties(fixture_html: str) -> None:
    """Parse card should extract parties (plaintiffs/defendants)."""
    parser = KadArbitrParser()
    summary = parser.parse_card(
        fixture_html,
        case_id="30f36558-ebdf-42d4-b576-436abc20b478",
        source_url="https://kad.arbitr.ru/Card/30f36558-ebdf-42d4-b576-436abc20b478",
    )

    assert len(summary.parties) == 2

    plaintiff = next((p for p in summary.parties if p.role == ParticipantRole.PLAINTIFF), None)
    assert plaintiff is not None
    assert 'АНОНИМ-КРЕДИТОР' in plaintiff.name

    defendant = next((p for p in summary.parties if p.role == ParticipantRole.DEFENDANT), None)
    assert defendant is not None
    assert 'АНОНИМ-ДОЛЖНИК' in defendant.name


def test_parse_card_extracts_judges(fixture_html: str) -> None:
    """Parse card should extract judge names."""
    parser = KadArbitrParser()
    summary = parser.parse_card(
        fixture_html,
        case_id="30f36558-ebdf-42d4-b576-436abc20b478",
        source_url="https://kad.arbitr.ru/Card/30f36558-ebdf-42d4-b576-436abc20b478",
    )

    assert len(summary.judges) == 1
    assert "Иванов И. И." in summary.judges


def test_parse_card_extracts_document_refs(fixture_html: str) -> None:
    """Parse card should extract document references.

    Note: статичная фикстура не содержит документов (загружаются динамически).
    Этот тест проверяет, что селектор не падает, возвращая пустой список.
    """
    parser = KadArbitrParser()
    summary = parser.parse_card(
        fixture_html,
        case_id="30f36558-ebdf-42d4-b576-436abc20b478",
        source_url="https://kad.arbitr.ru/Card/30f36558-ebdf-42d4-b576-436abc20b478",
    )

    assert isinstance(summary.document_refs, list)


def test_parse_card_handles_missing_optional_fields(minimal_html: str) -> None:
    """Parse card should handle missing optional fields without crashing."""
    parser = KadArbitrParser()
    summary = parser.parse_card(
        minimal_html,
        case_id="test-case-id-123",
        source_url="https://kad.arbitr.ru/Card/test-case-id-123",
    )

    assert summary.case_id == "test-case-id-123"
    assert summary.case_number == "А00-0000/2026"
    assert summary.court_name == "Тестовый АС"
    assert summary.instance_level == 1
    assert summary.dispute_category is None
    assert summary.parties == []
    assert summary.judges == []


@pytest.mark.asyncio
async def test_crawl_raises_not_implemented() -> None:
    """Crawl method should raise NotImplementedError."""
    parser = KadArbitrParser()

    with pytest.raises(NotImplementedError) as exc_info:
        async for _ in parser.crawl():
            pass

    assert "Stage 3c" in str(exc_info.value)


@pytest.mark.asyncio
async def test_fetch_document_raises_not_implemented() -> None:
    """Fetch document method should raise NotImplementedError."""
    parser = KadArbitrParser()

    with pytest.raises(NotImplementedError) as exc_info:
        await parser.fetch_document("test-id")

    assert "Stage 3c" in str(exc_info.value)


@pytest.mark.asyncio
async def test_parse_raises_not_implemented() -> None:
    """Parse method should raise NotImplementedError."""
    parser = KadArbitrParser()
    from datetime import datetime, timezone

    from app.parsers.schemas import RawDocument

    raw = RawDocument(
        source_id="test",
        source_name="arbitr",
        html="<html></html>",
        crawled_at=datetime.now(timezone.utc),
    )

    with pytest.raises(NotImplementedError) as exc_info:
        await parser.parse(raw)

    assert "Stage 3d" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_pdf_raises_not_implemented() -> None:
    """Get PDF method should raise NotImplementedError."""
    parser = KadArbitrParser()

    with pytest.raises(NotImplementedError) as exc_info:
        await parser.get_pdf("test-id")

    assert "Stage 3d" in str(exc_info.value)


@pytest.mark.asyncio
async def test_health_check_returns_true_on_200() -> None:
    """Health check should return True when server returns 200."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="OK")

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="kad",
        base_url="https://kad.arbitr.ru",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(transport=transport, base_url="https://kad.arbitr.ru")

        parser = KadArbitrParser(http_client=client)
        result = await parser.health_check()

        assert result is True


@pytest.mark.asyncio
async def test_health_check_returns_false_when_client_is_none() -> None:
    """Health check should return False when no client is provided."""
    parser = KadArbitrParser()
    result = await parser.health_check()

    assert result is False


@pytest.mark.asyncio
async def test_health_check_returns_false_on_exception() -> None:
    """Health check should return False when request raises exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection failed")

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="kad",
        base_url="https://kad.arbitr.ru",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(transport=transport, base_url="https://kad.arbitr.ru")

        parser = KadArbitrParser(http_client=client)
        result = await parser.health_check()

        assert result is False


def test_parse_chronology_extracts_documents() -> None:
    """Parse chronology should extract documents from CaseDocumentsPage response."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "kad_documents_response.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    parser = KadArbitrParser()
    refs = parser.parse_chronology(payload)

    assert len(refs) == 3
    assert all(ref.document_id for ref in refs)
    assert all(ref.document_date for ref in refs)
    assert all(ref.url for ref in refs)


def test_parse_chronology_raises_on_invalid_payload() -> None:
    """Parse chronology should raise ValueError on invalid payload."""
    parser = KadArbitrParser()

    with pytest.raises(ValueError) as exc_info:
        parser.parse_chronology({"Success": False})

    assert "Success != True" in str(exc_info.value)
