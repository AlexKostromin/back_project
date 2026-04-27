from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime, timezone

import structlog
from bs4 import BeautifulSoup

from app.parsers.base import BaseParser
from app.parsers.http import ResilientHttpClient
from app.parsers.kad import selectors
from app.parsers.kad.chronology import parse_chronology_response
from app.parsers.kad.schemas import DocumentRef, KadCaseSummary
from app.parsers.schemas import CourtType, ParsedDecision, RawDocument

logger = structlog.get_logger(__name__)


class KadArbitrParser(BaseParser):
    """Parser for kad.arbitr.ru case cards."""

    source_key = "arbitr"
    BASE_URL = "https://kad.arbitr.ru"

    def __init__(self, http_client: ResilientHttpClient | None = None) -> None:
        self._client = http_client

    async def health_check(self) -> bool:
        """Simple GET / check for KAD availability.

        At this stage, KAD behind DDoS-Guard returns 200 (challenge page).
        Full health check will be implemented in Stage 3c after KadSessionProvider.
        """
        if self._client is None:
            return False

        try:
            response = await self._client.get("/")
            return response.status_code == 200
        except Exception as exc:
            logger.warning("kad.health_check.failed", error=str(exc))
            return False

    async def crawl(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[RawDocument]:
        """Not yet implemented.

        Will be implemented in Stage 3c — POST /Kad/SearchInstances + KadSessionProvider.
        """
        raise NotImplementedError(
            "KadArbitrParser.crawl() появится в Stage 3c — POST /Kad/SearchInstances + KadSessionProvider"
        )
        yield  # pragma: no cover

    async def fetch_document(self, source_id: str) -> RawDocument:
        """Not yet implemented.

        Will be implemented in Stage 3c — GET /Card/{source_id}.
        """
        raise NotImplementedError(
            "KadArbitrParser.fetch_document() появится в Stage 3c — GET /Card/{source_id}"
        )

    async def parse(self, raw: RawDocument) -> ParsedDecision:
        """Not yet implemented.

        Will be implemented in Stage 3d — парсинг текста ДОКУМЕНТА (PDF/HTML), не карточки.
        Карточка парсится через parse_card() в KadCaseSummary.
        """
        raise NotImplementedError(
            "KadArbitrParser.parse() появится в Stage 3d — парсинг текста ДОКУМЕНТА (PDF/HTML), "
            "не карточки. Карточка парсится через parse_card() в KadCaseSummary."
        )

    async def get_pdf(self, source_id: str) -> bytes | None:
        """Not yet implemented.

        Will be implemented in Stage 3d — скачивание PDF документа.
        """
        raise NotImplementedError(
            "KadArbitrParser.get_pdf() появится в Stage 3d — скачивание PDF документа"
        )

    def parse_card(self, html: str, *, case_id: str, source_url: str) -> KadCaseSummary:
        """Parse HTML card from kad.arbitr.ru/Card/{uuid} → KadCaseSummary.

        Sync function (BS4 — CPU-bound, no I/O), returns summary.
        case_id and source_url are passed explicitly because URL cannot always be reliably recovered from card HTML.

        Note: document_refs will always be empty — documents come from separate AJAX call.
        Use parse_chronology() to populate documents from CaseDocumentsPage response.
        """
        soup = BeautifulSoup(html, "lxml")

        extracted_case_id = selectors.extract_case_id(soup)
        case_number = selectors.extract_case_number(soup)
        court_name = selectors.extract_court_name(soup)
        instance_level = selectors.extract_instance_level(soup)
        dispute_category = selectors.extract_dispute_category(soup)
        parties = selectors.extract_parties(soup)
        judges = selectors.extract_judges(soup)

        if extracted_case_id != case_id:
            logger.warning(
                "kad.parse_card.case_id_mismatch",
                provided=case_id,
                extracted=extracted_case_id,
            )

        return KadCaseSummary(
            case_id=case_id,
            case_number=case_number,
            court_name=court_name,
            court_type=CourtType.ARBITRAZH,
            instance_level=instance_level,
            region=None,
            dispute_category=dispute_category,
            parties=parties,
            judges=judges,
            document_refs=[],
            source_url=source_url,
            crawled_at=datetime.now(timezone.utc),
        )

    def parse_chronology(self, payload: dict) -> list[DocumentRef]:
        """Parse CaseDocumentsPage AJAX response to list of DocumentRef.

        Sync function (JSON parsing — CPU-bound, no I/O).
        Wrapper over chronology.parse_chronology_response.

        Args:
            payload: Parsed JSON response from /Kad/CaseDocumentsPage

        Returns:
            List of DocumentRef objects

        Raises:
            ValueError: If payload is invalid
        """
        return parse_chronology_response(payload)
