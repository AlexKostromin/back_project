from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _raw_payload(
    *,
    source_id: str,
    case_number: str,
    full_text: str,
    decision_date: str = "2025-06-01",
    court_type: str = "arbitrazh",
    region: str | None = "Москва",
    doc_type: str = "решение",
    result: str | None = "satisfied",
    appeal_status: str | None = "none",
    dispute_type: str | None = "civil",
    claim_amount: str | None = "100000.00",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_name": "arbitr",
        "case_number": case_number,
        "court_name": "Арбитражный суд города Москвы",
        "court_type": court_type,
        "instance_level": 1,
        "region": region,
        "decision_date": decision_date,
        "publication_date": None,
        "doc_type": doc_type,
        "judges": ["Иванов И.И."],
        "result": result,
        "appeal_status": appeal_status,
        "dispute_type": dispute_type,
        "category": None,
        "claim_amount": claim_amount,
        "participants": [],
        "norms": [],
        "full_text": full_text,
        "sections": None,
        "source_url": "https://kad.arbitr.ru/Card/xxx",
        "raw_html": None,
        "pdf_url": None,
    }


async def _ingest(client: AsyncClient, payload: dict[str, Any]) -> int:
    response = await client.post("/api/v1/search/ingest/decision", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["decision_id"]


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_data(clean_search_tables, clean_es_index) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/search/decisions", json={})

    assert response.status_code == 200
    body = response.json()
    assert body == {"total": 0, "page": 1, "page_size": 20, "items": []}


@pytest.mark.asyncio
async def test_search_filters_by_court_type_and_date_range(
    clean_search_tables, clean_es_index,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="a-1",
                case_number="А40-1/2025",
                full_text="арбитражный текст 1",
                decision_date="2025-01-10",
                court_type="arbitrazh",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="a-2",
                case_number="А40-2/2025",
                full_text="арбитражный текст 2",
                decision_date="2025-03-15",
                court_type="arbitrazh",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="s-1",
                case_number="2-100/2025",
                full_text="соу текст",
                decision_date="2025-02-20",
                court_type="soy",
            ),
        )

        response = await client.post(
            "/api/v1/search/decisions",
            json={
                "court_type": "arbitrazh",
                "date_from": "2025-02-01",
                "date_to": "2025-12-31",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["case_number"] == "А40-2/2025"
    assert body["items"][0]["court_type"] == "arbitrazh"


@pytest.mark.asyncio
async def test_search_sort_date_desc_is_default(clean_search_tables, clean_es_index) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="d-1",
                case_number="А40-10/2025",
                full_text="t1",
                decision_date="2025-01-10",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="d-2",
                case_number="А40-20/2025",
                full_text="t2",
                decision_date="2025-05-10",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="d-3",
                case_number="А40-30/2025",
                full_text="t3",
                decision_date="2025-03-10",
            ),
        )

        response = await client.post("/api/v1/search/decisions", json={})

    assert response.status_code == 200
    body = response.json()
    dates = [item["decision_date"] for item in body["items"]]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.asyncio
async def test_search_sort_date_asc(clean_search_tables, clean_es_index) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="a-1",
                case_number="А40-10/2025",
                full_text="t1",
                decision_date="2025-05-10",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="a-2",
                case_number="А40-20/2025",
                full_text="t2",
                decision_date="2025-01-10",
            ),
        )

        response = await client.post(
            "/api/v1/search/decisions", json={"sort_by": "date_asc"}
        )

    assert response.status_code == 200
    body = response.json()
    dates = [item["decision_date"] for item in body["items"]]
    assert dates == sorted(dates)


@pytest.mark.asyncio
async def test_search_pagination(clean_search_tables, clean_es_index) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for i in range(5):
            await _ingest(
                client,
                _raw_payload(
                    source_id=f"p-{i}",
                    case_number=f"А40-{i}/2025",
                    full_text=f"текст {i}",
                    decision_date=f"2025-01-{10 + i:02d}",
                ),
            )

        page1 = await client.post(
            "/api/v1/search/decisions",
            json={"page": 1, "page_size": 2, "sort_by": "date_asc"},
        )
        page2 = await client.post(
            "/api/v1/search/decisions",
            json={"page": 2, "page_size": 2, "sort_by": "date_asc"},
        )
        page3 = await client.post(
            "/api/v1/search/decisions",
            json={"page": 3, "page_size": 2, "sort_by": "date_asc"},
        )

    assert page1.json()["total"] == 5
    assert len(page1.json()["items"]) == 2
    assert len(page2.json()["items"]) == 2
    assert len(page3.json()["items"]) == 1

    ids = [
        *[i["id"] for i in page1.json()["items"]],
        *[i["id"] for i in page2.json()["items"]],
        *[i["id"] for i in page3.json()["items"]],
    ]
    assert len(set(ids)) == 5


@pytest.mark.asyncio
async def test_search_claim_amount_range(clean_search_tables, clean_es_index) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="m-1",
                case_number="А40-1/2025",
                full_text="мало",
                claim_amount="500.00",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="m-2",
                case_number="А40-2/2025",
                full_text="средне",
                claim_amount="5000.00",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="m-3",
                case_number="А40-3/2025",
                full_text="много",
                claim_amount="50000.00",
            ),
        )

        response = await client.post(
            "/api/v1/search/decisions",
            json={"claim_amount_min": "1000", "claim_amount_max": "10000"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["case_number"] == "А40-2/2025"


@pytest.mark.asyncio
async def test_search_rejects_inverted_date_range(clean_search_tables, clean_es_index) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/decisions",
            json={"date_from": "2025-12-01", "date_to": "2025-01-01"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_snippet_is_truncated(clean_search_tables, clean_es_index) -> None:
    long_text = "А" * 1000
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="snip-1",
                case_number="А40-SNIP/2025",
                full_text=long_text,
            ),
        )

        response = await client.post("/api/v1/search/decisions", json={})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert len(item["snippet"]) == 300
    assert item["snippet"] == "А" * 300
