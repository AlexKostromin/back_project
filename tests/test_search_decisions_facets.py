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
async def test_facets_empty_when_no_data(
    clean_search_tables, clean_es_index,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/search/decisions/facets", json={})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "total": 0,
        "court_type": [],
        "dispute_type": [],
        "result": [],
        "region": [],
        "decisions_by_month": [],
    }


@pytest.mark.asyncio
async def test_facets_terms_aggregations_count_correctly(
    clean_search_tables, clean_es_index,
) -> None:
    # 3 × arbitrazh + satisfied, 2 × soy + denied. Case numbers are unique
    # so ingest doesn't dedup by text_hash.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for i in range(3):
            await _ingest(
                client,
                _raw_payload(
                    source_id=f"a-{i}",
                    case_number=f"А40-{i}/2025",
                    full_text=f"арбитражный текст {i}",
                    court_type="arbitrazh",
                    result="satisfied",
                ),
            )
        for i in range(2):
            await _ingest(
                client,
                _raw_payload(
                    source_id=f"s-{i}",
                    case_number=f"2-{i}/2025",
                    full_text=f"соу текст {i}",
                    court_type="soy",
                    result="denied",
                ),
            )

        response = await client.post("/api/v1/search/decisions/facets", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5

    court_type = {b["key"]: b["count"] for b in body["court_type"]}
    assert court_type == {"arbitrazh": 3, "soy": 2}

    result = {b["key"]: b["count"] for b in body["result"]}
    assert result == {"satisfied": 3, "denied": 2}

    # ES terms aggregation guarantees count desc ordering; the top bucket
    # must be the majority one.
    assert body["court_type"][0] == {"key": "arbitrazh", "count": 3}
    assert body["result"][0] == {"key": "satisfied", "count": 3}


@pytest.mark.asyncio
async def test_facets_region_uses_keyword_subfield(
    clean_search_tables, clean_es_index,
) -> None:
    # "Санкт-Петербург" would otherwise be tokenised by the russian
    # analyzer into "санкт" + "петербург" — aggregation on the `.raw`
    # keyword sub-field must keep it whole.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="r-1",
                case_number="А40-R1/2025",
                full_text="текст один",
                region="Санкт-Петербург",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="r-2",
                case_number="А40-R2/2025",
                full_text="текст два",
                region="Санкт-Петербург",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="r-3",
                case_number="А40-R3/2025",
                full_text="текст три",
                region="Москва",
            ),
        )

        response = await client.post("/api/v1/search/decisions/facets", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    region = {b["key"]: b["count"] for b in body["region"]}
    assert region == {"Санкт-Петербург": 2, "Москва": 1}
    assert body["region"][0] == {"key": "Санкт-Петербург", "count": 2}


@pytest.mark.asyncio
async def test_facets_date_histogram_groups_by_month(
    clean_search_tables, clean_es_index,
) -> None:
    # Two docs in Jan 2025, one in Mar 2025. Feb has no docs; with
    # min_doc_count=1 it must be absent from the histogram. Buckets must
    # be chronological.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="h-1",
                case_number="А40-H1/2025",
                full_text="январь 1",
                decision_date="2025-01-15",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="h-2",
                case_number="А40-H2/2025",
                full_text="январь 2",
                decision_date="2025-01-28",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="h-3",
                case_number="А40-H3/2025",
                full_text="март 1",
                decision_date="2025-03-10",
            ),
        )

        response = await client.post("/api/v1/search/decisions/facets", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["decisions_by_month"] == [
        {"month": "2025-01-01", "count": 2},
        {"month": "2025-03-01", "count": 1},
    ]


@pytest.mark.asyncio
async def test_facets_respect_filters(
    clean_search_tables, clean_es_index,
) -> None:
    # The filter must be applied to the aggregations too, not just to the
    # total count — otherwise counting bars would contradict the list.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for i in range(3):
            await _ingest(
                client,
                _raw_payload(
                    source_id=f"af-{i}",
                    case_number=f"А40-F{i}/2025",
                    full_text=f"арбитраж {i}",
                    court_type="arbitrazh",
                ),
            )
        for i in range(2):
            await _ingest(
                client,
                _raw_payload(
                    source_id=f"sf-{i}",
                    case_number=f"2-F{i}/2025",
                    full_text=f"соу {i}",
                    court_type="soy",
                ),
            )

        response = await client.post(
            "/api/v1/search/decisions/facets",
            json={"court_type": "arbitrazh"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["court_type"] == [{"key": "arbitrazh", "count": 3}]


@pytest.mark.asyncio
async def test_facets_respect_query(
    clean_search_tables, clean_es_index,
) -> None:
    # Only docs that contain "налог" should feed the aggregations; the
    # trudovoy-spor doc is excluded from both total and terms. NB: the
    # russian stemmer maps "налоговый" → "налогов", which would *not*
    # match a bare "налог" query, so we use the exact noun form here.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="q-1",
                case_number="А40-Q1/2025",
                full_text="налог уплата взыскание",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="q-2",
                case_number="А40-Q2/2025",
                full_text="трудовой спор с восстановлением",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="q-3",
                case_number="А40-Q3/2025",
                full_text="налог решение по делу",
            ),
        )

        response = await client.post(
            "/api/v1/search/decisions/facets",
            json={"query": "налог"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    # Both matching docs share court_type/dispute_type from the default
    # payload, so the buckets must sum to 2 — the trudovoy doc is out.
    court_type = {b["key"]: b["count"] for b in body["court_type"]}
    assert court_type == {"arbitrazh": 2}
    dispute_type = {b["key"]: b["count"] for b in body["dispute_type"]}
    assert dispute_type == {"civil": 2}


@pytest.mark.asyncio
async def test_facets_rejects_pagination_fields(
    clean_search_tables, clean_es_index,
) -> None:
    # FacetsRequest has extra="forbid" and intentionally does not declare
    # page/page_size/sort_by — any attempt to pass them must 422.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/decisions/facets",
            json={"page": 1},
        )

    assert response.status_code == 422
    # Best-effort sanity check on the error payload — Pydantic v2 "extra
    # forbidden" wording mentions the offending field name.
    detail_blob = str(response.json()).lower()
    assert "page" in detail_blob or "extra" in detail_blob
