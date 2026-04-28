from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone

import structlog
from bs4 import BeautifulSoup

from app.parsers.base import BaseParser
from app.parsers.http import ResilientHttpClient
from app.parsers.kad import selectors
from app.parsers.kad.chronology import parse_chronology_response
from app.parsers.kad.schemas import DocumentRef, KadCaseSummary
from app.parsers.kad.session import KadSessionProvider
from app.parsers.schemas import CourtType, ParsedDecision, RawDocument

logger = structlog.get_logger(__name__)

# Hard cap on accumulated DocumentRefs across all pages of one case.
# 100 pages * 1000 items per page (the per-page cap from chronology.py) = 100k —
# unbounded in memory. Real cases have at most a few hundred documents; bankruptcy
# extremes maybe a few thousand. 10k is generous and prevents OOM if the upstream
# pagination logic misbehaves.
MAX_TOTAL_REFS = 10_000


class KadArbitrParser(BaseParser):
    """Parser for kad.arbitr.ru case cards."""

    source_key = "arbitr"
    BASE_URL = "https://kad.arbitr.ru"

    def __init__(
        self,
        http_client: ResilientHttpClient | None = None,
        session_provider: KadSessionProvider | None = None,
    ) -> None:
        self._client = http_client
        self._session = session_provider

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

    async def fetch_chronology(self, case_id: str) -> list[DocumentRef]:
        """Fetch all document references for a case via /Kad/CaseDocumentsPage.

        Handles pagination internally, accumulating across all pages.
        Validates case_id as UUID before sending (defense in depth: case_id
        goes into URL params and Referer header).

        Args:
            case_id: Case UUID (validated before request)

        Returns:
            List of DocumentRef objects from all pages

        Raises:
            RuntimeError: If http_client or session_provider not configured
            ValueError: If case_id is not a valid UUID
            httpx.HTTPStatusError: If server returns 4xx/5xx (after retries)
        """
        if self._client is None or self._session is None:
            raise RuntimeError(
                "fetch_chronology requires http_client and session_provider"
            )

        # Validate case_id is UUID (defense in depth)
        try:
            uuid.UUID(case_id)
        except ValueError as exc:
            raise ValueError(f"case_id must be a valid UUID, got: {case_id!r}") from exc

        logger.info("kad.fetch_chronology.start", case_id=case_id)

        cookies_obj = await self._session.get_cookies()
        all_refs: list[DocumentRef] = []
        page = 1
        pages_count = 1

        while page <= pages_count:
            page_refs = await self._fetch_chronology_page(
                case_id=case_id,
                page=page,
                cookies=cookies_obj.cookies,
            )

            all_refs.extend(page_refs.refs)
            pages_count = page_refs.pages_count

            if page_refs.pages_count == 0 or not page_refs.refs:
                break

            # Total-refs cap: prevent OOM via 100 pages * 1000 items.
            if len(all_refs) >= MAX_TOTAL_REFS:
                logger.warning(
                    "kad.fetch_chronology.max_refs_reached",
                    case_id=case_id,
                    refs=len(all_refs),
                    limit=MAX_TOTAL_REFS,
                )
                break

            page += 1

            # Hard cap: protect against infinite loop if server misbehaves
            if page > 100:
                logger.warning(
                    "kad.fetch_chronology.max_pages_reached",
                    case_id=case_id,
                    pages_processed=100,
                )
                break

        logger.info(
            "kad.fetch_chronology.complete",
            case_id=case_id,
            pages=page - 1,
            refs=len(all_refs),
        )

        return all_refs

    async def _fetch_chronology_page(
        self,
        case_id: str,
        page: int,
        cookies: dict[str, str],
    ) -> _ChronologyPageResult:
        """Fetch and parse a single page from /Kad/CaseDocumentsPage.

        Internal helper extracted to keep fetch_chronology under 30 lines.

        Returns:
            Parsed page with refs and pagination metadata
        """
        if self._client is None:
            raise RuntimeError("http_client is None")

        params = {
            "caseId": case_id,
            "page": page,
            "perPage": 25,
            "_": int(time.time() * 1000),
        }

        # Defense in depth: validate cookies before building the header manually.
        # Cookies come from KadSessionProvider (we control the source today),
        # but a CRLF in a cookie value would let an attacker inject arbitrary
        # HTTP headers via the Cookie line. Empty dict means session bug —
        # better fail loudly than send a malformed empty Cookie: header.
        if not cookies:
            raise RuntimeError(
                "session provider returned empty cookies; cannot fetch chronology"
            )
        for k, v in cookies.items():
            if "\r" in k or "\n" in k or "\r" in v or "\n" in v:
                raise ValueError(f"cookie {k!r} contains CRLF; refusing to send")

        cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())

        headers = {
            "Accept": "application/json, text/javascript, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self.BASE_URL}/Card/{case_id}",
            "Cookie": cookie_header,
        }

        # follow_redirects=False is httpx default, but be explicit: an AJAX
        # endpoint that 302s is anomalous and shouldn't leak Referer (with
        # case_id) to a third-party host.
        response = await self._client.get(
            "/Kad/CaseDocumentsPage",
            params=params,
            headers=headers,
            follow_redirects=False,
        )

        response.raise_for_status()
        payload = response.json()

        refs = parse_chronology_response(payload)
        pages_count = payload.get("Result", {}).get("PagesCount", 0)

        return _ChronologyPageResult(refs=refs, pages_count=pages_count)

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


class _ChronologyPageResult:
    """Internal result container for single page from CaseDocumentsPage."""

    def __init__(self, refs: list[DocumentRef], pages_count: int) -> None:
        self.refs = refs
        self.pages_count = pages_count
