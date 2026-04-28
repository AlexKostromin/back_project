from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.parsers.http import CircuitBreaker, RateLimiter, ResilientHttpClient, RetryPolicy
from app.parsers.kad.parser import KadArbitrParser
from app.parsers.kad.session import KadSessionProvider, PlaywrightKadSessionProvider, SessionCookies


class _FixedCookiesSession(KadSessionProvider):
    """Fake session provider for unit tests."""

    def __init__(self, cookies: dict[str, str]) -> None:
        self._fixed = cookies

    async def get_cookies(self) -> SessionCookies:
        return SessionCookies(
            cookies=self._fixed,
            obtained_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )


@pytest.fixture
def mock_cookies() -> dict[str, str]:
    """Standard DDoS-Guard cookies for tests."""
    return {
        "__ddg8_": "test_ddg8_value",
        "__ddg9_": "test_ddg9_value",
        "__ddg10_": "test_ddg10_value",
        "ASP.NET_SessionId": "test_session_id",
    }


@pytest.fixture
def sample_fixture() -> dict[str, Any]:
    """Load kad_documents_response.json fixture."""
    fixture_path = "tests/parsers/fixtures/kad_documents_response.json"
    with open(fixture_path, encoding="utf-8") as f:
        return json.load(f)


def make_response_payload(
    items: list[dict[str, Any]],
    page: int,
    pages_count: int,
    total_count: int,
) -> dict[str, Any]:
    """Build CaseDocumentsPage response payload."""
    return {
        "Result": {
            "Page": page,
            "PageSize": 25,
            "TotalCount": total_count,
            "PagesCount": pages_count,
            "Items": items,
            "Count": len(items),
        },
        "Message": "",
        "Success": True,
        "ServerDate": "/Date(1777275963481)/",
    }


@pytest.mark.asyncio
async def test_fetch_chronology_single_page(
    sample_fixture: dict[str, Any],
    mock_cookies: dict[str, str],
) -> None:
    """Happy path: single page with 3 documents."""
    test_case_id = "00000000-0000-0000-0000-00000000ca5e"
    received_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received_requests.append(request)
        return httpx.Response(200, json=sample_fixture)

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="https://kad.arbitr.ru",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport,
            base_url="https://kad.arbitr.ru",
        )

        session = _FixedCookiesSession(mock_cookies)
        parser = KadArbitrParser(http_client=client, session_provider=session)

        refs = await parser.fetch_chronology(test_case_id)

        # Should return 3 refs from fixture
        assert len(refs) == 3

        # Verify request was made correctly
        assert len(received_requests) == 1
        req = received_requests[0]

        # Check URL and path
        assert req.url.path == "/Kad/CaseDocumentsPage"

        # Check query params
        parsed_url = urlparse(str(req.url))
        params = parse_qs(parsed_url.query)
        assert params["caseId"][0] == test_case_id
        assert params["page"][0] == "1"
        assert params["perPage"][0] == "25"
        assert "_" in params  # timestamp present

        # Check headers
        assert req.headers["X-Requested-With"] == "XMLHttpRequest"
        assert req.headers["Accept"] == "application/json, text/javascript, */*"
        assert req.headers["Referer"] == f"https://kad.arbitr.ru/Card/{test_case_id}"

        # Check cookies were sent
        # httpx passes cookies via Cookie header
        assert "Cookie" in req.headers


@pytest.mark.asyncio
async def test_fetch_chronology_paginates_multiple_pages(
    sample_fixture: dict[str, Any],
    mock_cookies: dict[str, str],
) -> None:
    """Pagination: 2 pages with 25 + 5 items."""
    test_case_id = "00000000-0000-0000-0000-00000000ca5e"
    received_pages: list[int] = []

    # Use first item from fixture as template
    template_item = sample_fixture["Result"]["Items"][0]

    def handler(request: httpx.Request) -> httpx.Response:
        parsed_url = urlparse(str(request.url))
        params = parse_qs(parsed_url.query)
        page = int(params["page"][0])
        received_pages.append(page)

        if page == 1:
            # First page: 25 items
            items = [template_item for _ in range(25)]
            payload = make_response_payload(
                items=items,
                page=1,
                pages_count=2,
                total_count=30,
            )
            return httpx.Response(200, json=payload)
        elif page == 2:
            # Second page: 5 items
            items = [template_item for _ in range(5)]
            payload = make_response_payload(
                items=items,
                page=2,
                pages_count=2,
                total_count=30,
            )
            return httpx.Response(200, json=payload)
        else:
            # Should not request page 3
            return httpx.Response(400, json={"Success": False})

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="https://kad.arbitr.ru",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport,
            base_url="https://kad.arbitr.ru",
        )

        session = _FixedCookiesSession(mock_cookies)
        parser = KadArbitrParser(http_client=client, session_provider=session)

        refs = await parser.fetch_chronology(test_case_id)

        # Should return 30 total refs (25 + 5)
        assert len(refs) == 30

        # Should have made exactly 2 requests
        assert received_pages == [1, 2]


@pytest.mark.asyncio
async def test_fetch_chronology_empty_response(
    mock_cookies: dict[str, str],
) -> None:
    """Empty result: PagesCount=0, Items=[]."""
    test_case_id = "00000000-0000-0000-0000-00000000ca5e"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = make_response_payload(
            items=[],
            page=1,
            pages_count=0,
            total_count=0,
        )
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="https://kad.arbitr.ru",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport,
            base_url="https://kad.arbitr.ru",
        )

        session = _FixedCookiesSession(mock_cookies)
        parser = KadArbitrParser(http_client=client, session_provider=session)

        refs = await parser.fetch_chronology(test_case_id)

        assert refs == []


@pytest.mark.asyncio
async def test_fetch_chronology_invalid_case_id_uuid(
    mock_cookies: dict[str, str],
) -> None:
    """ValueError if case_id is not a valid UUID."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="https://kad.arbitr.ru",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport,
            base_url="https://kad.arbitr.ru",
        )

        session = _FixedCookiesSession(mock_cookies)
        parser = KadArbitrParser(http_client=client, session_provider=session)

        with pytest.raises(ValueError, match="case_id must be a valid UUID"):
            await parser.fetch_chronology("not-a-uuid")


@pytest.mark.asyncio
async def test_fetch_chronology_requires_http_client(
    mock_cookies: dict[str, str],
) -> None:
    """RuntimeError if http_client is None."""
    session = _FixedCookiesSession(mock_cookies)
    parser = KadArbitrParser(http_client=None, session_provider=session)

    with pytest.raises(RuntimeError, match="fetch_chronology requires http_client"):
        await parser.fetch_chronology("00000000-0000-0000-0000-00000000ca5e")


@pytest.mark.asyncio
async def test_fetch_chronology_requires_session_provider(
    mock_cookies: dict[str, str],
) -> None:
    """RuntimeError if session_provider is None."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="https://kad.arbitr.ru",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport,
            base_url="https://kad.arbitr.ru",
        )

        parser = KadArbitrParser(http_client=client, session_provider=None)

        with pytest.raises(RuntimeError, match="fetch_chronology requires"):
            await parser.fetch_chronology("00000000-0000-0000-0000-00000000ca5e")


@pytest.mark.asyncio
async def test_fetch_chronology_propagates_http_errors(
    mock_cookies: dict[str, str],
) -> None:
    """500 response raises HTTPStatusError (after ResilientHttpClient retries)."""
    test_case_id = "00000000-0000-0000-0000-00000000ca5e"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"Success": False})

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="https://kad.arbitr.ru",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport,
            base_url="https://kad.arbitr.ru",
        )

        session = _FixedCookiesSession(mock_cookies)
        parser = KadArbitrParser(http_client=client, session_provider=session)

        # ResilientHttpClient will retry 3 times, then raise MaxRetriesError
        # which wraps HTTPStatusError
        from app.parsers.exceptions import MaxRetriesError

        with pytest.raises(MaxRetriesError):
            await parser.fetch_chronology(test_case_id)


@pytest.mark.asyncio
async def test_fetch_chronology_max_pages_safety(
    sample_fixture: dict[str, Any],
    mock_cookies: dict[str, str],
) -> None:
    """Safety: stops after 100 pages even if server claims more."""
    test_case_id = "00000000-0000-0000-0000-00000000ca5e"
    template_item = sample_fixture["Result"]["Items"][0]
    pages_requested: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        parsed_url = urlparse(str(request.url))
        params = parse_qs(parsed_url.query)
        page = int(params["page"][0])
        pages_requested.append(page)

        # Server claims 999 pages
        payload = make_response_payload(
            items=[template_item],
            page=page,
            pages_count=999,
            total_count=24975,
        )
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="https://kad.arbitr.ru",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport,
            base_url="https://kad.arbitr.ru",
        )

        session = _FixedCookiesSession(mock_cookies)
        parser = KadArbitrParser(http_client=client, session_provider=session)

        # Wrap in asyncio.wait_for to prevent infinite loop in case of bug
        # 100 pages with rate limit 10 req/s takes ~10s, plus overhead
        refs = await asyncio.wait_for(
            parser.fetch_chronology(test_case_id),
            timeout=15.0,
        )

        # Should stop at page 100 (hard cap)
        assert len(pages_requested) == 100
        assert len(refs) == 100  # 100 pages * 1 item each


@pytest.mark.asyncio
async def test_fetch_chronology_rejects_crlf_in_cookie_values() -> None:
    """Cookie value with CRLF must trigger ValueError (header injection guard)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not reach upstream when cookies are unsafe")

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="https://kad.arbitr.ru",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=1, base_delay=0.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport,
            base_url="https://kad.arbitr.ru",
        )

        unsafe = {"__ddg9_": "ip\r\nX-Admin: true"}
        session = _FixedCookiesSession(unsafe)
        parser = KadArbitrParser(http_client=client, session_provider=session)

        with pytest.raises(ValueError, match="CRLF"):
            await parser.fetch_chronology("00000000-0000-0000-0000-00000000ca5e")


@pytest.mark.asyncio
async def test_fetch_chronology_rejects_empty_cookies() -> None:
    """Empty cookies dict from session provider must fail loudly."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not reach upstream with empty cookies")

    transport = httpx.MockTransport(handler)

    async with ResilientHttpClient(
        source_name="test",
        base_url="https://kad.arbitr.ru",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=10.0),
        retry=RetryPolicy(max_attempts=1, base_delay=0.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport,
            base_url="https://kad.arbitr.ru",
        )

        session = _FixedCookiesSession({})
        parser = KadArbitrParser(http_client=client, session_provider=session)

        with pytest.raises(RuntimeError, match="empty cookies"):
            await parser.fetch_chronology("00000000-0000-0000-0000-00000000ca5e")


@pytest.mark.skipif(
    os.environ.get("KAD_INTEGRATION_TESTS") != "1",
    reason="Live KAD test, requires KAD_INTEGRATION_TESTS=1 + chromium installed",
)
@pytest.mark.asyncio
async def test_fetch_chronology_live() -> None:
    """Integration test: fetch real chronology from kad.arbitr.ru."""
    # Known case from fixture (check if still available)
    test_case_id = "c16fd0be-7afe-42db-90f6-dfb8e74c2ac1"

    async with ResilientHttpClient(
        source_name="kad",
        base_url="https://kad.arbitr.ru",
        rate_limit=RateLimiter(capacity=10, refill_per_sec=2.0),
        retry=RetryPolicy(max_attempts=3, base_delay=1.0),
        circuit=CircuitBreaker(window_size=20, failure_threshold=0.3, cooldown_sec=60.0),
    ) as client:
        session = PlaywrightKadSessionProvider()
        parser = KadArbitrParser(http_client=client, session_provider=session)

        refs = await parser.fetch_chronology(test_case_id)

        # Should return at least some documents
        assert len(refs) > 0
        # All refs should have required fields
        for ref in refs:
            assert ref.document_id
            assert ref.document_date
            assert ref.url
