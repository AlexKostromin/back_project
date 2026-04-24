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


@pytest.mark.asyncio
async def test_search_query_matches_full_text(clean_search_tables, clean_es_index) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="q-1",
                case_number="А40-Q1/2025",
                full_text="иск о взыскании задолженности",
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
                full_text="административное правонарушение ГИБДД",
            ),
        )

        response = await client.post(
            "/api/v1/search/decisions", json={"query": "задолженности"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["case_number"] == "А40-Q1/2025"


@pytest.mark.asyncio
async def test_search_query_no_match_returns_empty(
    clean_search_tables, clean_es_index,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="nm-1",
                case_number="А40-NM/2025",
                full_text="иск о взыскании задолженности",
            ),
        )

        response = await client.post(
            "/api/v1/search/decisions", json={"query": "абсолютно_несуществующее_слово"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_search_query_highlight_populates_snippet(
    clean_search_tables, clean_es_index,
) -> None:
    # Build a ~1000-char full_text composed of real word-tokens (so the ES
    # highlighter has break-points at which to cut a ~300-char fragment)
    # with a distinctive marker in the middle. If highlight kicks in,
    # the snippet centres on the marker and differs from the static
    # "first 300 chars" fallback.
    word_head = "альфа "
    word_tail = "омега "
    needle = "УНИКАЛЬНОЕ"
    prefix = word_head * 80  # ~480 chars, tokenised
    suffix = word_tail * 80  # ~480 chars, tokenised
    full_text = f"{prefix}{needle} {suffix}".strip()
    assert 950 <= len(full_text) <= 1100

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="hl-1",
                case_number="А40-HL/2025",
                full_text=full_text,
            ),
        )

        response = await client.post(
            "/api/v1/search/decisions", json={"query": needle}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    snippet = body["items"][0]["snippet"]
    # Highlight kicked in → snippet contains the match and is not the
    # static "first 300 chars" fallback (which is pure 'альфа ' repeats).
    assert needle in snippet
    assert snippet != full_text[:300]
    # fragment_size=300, but ES may overshoot a few chars on the token
    # boundary — allow a small slack.
    assert len(snippet) <= 310


@pytest.mark.asyncio
async def test_search_filters_by_region_uses_keyword_subfield(
    clean_search_tables, clean_es_index,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="r-1",
                case_number="А40-R1/2025",
                full_text="текст один",
                region="Москва",
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

        response = await client.post(
            "/api/v1/search/decisions", json={"region": "Санкт-Петербург"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["case_number"] == "А40-R2/2025"
    assert body["items"][0]["region"] == "Санкт-Петербург"


@pytest.mark.asyncio
async def test_search_query_and_filters_combine(
    clean_search_tables, clean_es_index,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="c-1",
                case_number="А40-C1/2025",
                full_text="иск о взыскании",
                court_type="arbitrazh",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="c-2",
                case_number="А40-C2/2025",
                full_text="иск о разделе",
                court_type="arbitrazh",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="c-3",
                case_number="2-300/2025",
                full_text="иск о выселении",
                court_type="soy",
            ),
        )

        response = await client.post(
            "/api/v1/search/decisions",
            json={"query": "иск", "court_type": "soy"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["case_number"] == "2-300/2025"
    assert body["items"][0]["court_type"] == "soy"


@pytest.mark.asyncio
async def test_search_sort_relevance_orders_by_score(
    clean_search_tables, clean_es_index,
) -> None:
    # Three docs with identical dates — so any ordering difference comes
    # from BM25 score, not the date tiebreaker. HIGH repeats "налог" many
    # times in a short text (high TF); MID has two occurrences; LOW has a
    # single occurrence diluted across a long text (low TF-IDF). With
    # ``sort_by=relevance`` we expect HIGH first, LOW last.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _ingest(
            client,
            _raw_payload(
                source_id="rel-high",
                case_number="А40-HIGH/2025",
                full_text="налог налог налог налог налог налог",
                decision_date="2025-06-01",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="rel-mid",
                case_number="А40-MID/2025",
                full_text="налог налог и прочие вопросы гражданского права",
                decision_date="2025-06-01",
            ),
        )
        await _ingest(
            client,
            _raw_payload(
                source_id="rel-low",
                case_number="А40-LOW/2025",
                full_text=(
                    "один единственный налог в огромном корпусе слов про "
                    "договоры поставки и прочую коммерцию хозяйственную "
                    "деятельность юридических лиц"
                ),
                decision_date="2025-06-01",
            ),
        )

        response = await client.post(
            "/api/v1/search/decisions",
            json={"query": "налог", "sort_by": "relevance"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    items = body["items"]
    assert len(items) == 3
    assert items[0]["case_number"] == "А40-HIGH/2025"
    assert items[-1]["case_number"] == "А40-LOW/2025"


@pytest.mark.asyncio
async def test_search_sort_relevance_without_query_is_rejected(
    clean_search_tables, clean_es_index,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/decisions",
            json={"sort_by": "relevance"},
        )

    assert response.status_code == 422
    # Best-effort sanity check on the error payload — Pydantic v2 nests
    # validator messages under ``detail[*].msg``. We don't hard-fail if
    # the wording drifts, only if neither hint is present anywhere.
    detail_blob = str(response.json()).lower()
    assert "relevance" in detail_blob or "query" in detail_blob


@pytest.mark.asyncio
async def test_search_sort_relevance_paginates_stably(
    clean_search_tables, clean_es_index,
) -> None:
    # Four docs with the same searchable term ("налог") and dates → the
    # BM25 score for ``query=налог`` is identical across them (one match
    # in a two-token field, same collection stats). Each text has a
    # trailing integer so ``text_hash`` differs and the ingest pipeline
    # doesn't deduplicate. Without a deterministic tiebreaker, ES could
    # return the same doc on both pages (or skip one); the repository
    # adds ``id`` as a secondary sort key, so page 1 ∪ page 2 must yield
    # exactly four distinct ids.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for i in range(4):
            await _ingest(
                client,
                _raw_payload(
                    source_id=f"rel-tie-{i}",
                    case_number=f"А40-TIE{i}/2025",
                    full_text=f"налог {i}",
                    decision_date="2025-06-01",
                ),
            )

        page1 = await client.post(
            "/api/v1/search/decisions",
            json={
                "query": "налог",
                "sort_by": "relevance",
                "page_size": 2,
                "page": 1,
            },
        )
        page2 = await client.post(
            "/api/v1/search/decisions",
            json={
                "query": "налог",
                "sort_by": "relevance",
                "page_size": 2,
                "page": 2,
            },
        )

    assert page1.status_code == 200
    assert page2.status_code == 200

    p1_body = page1.json()
    p2_body = page2.json()
    assert p1_body["total"] == 4
    assert p2_body["total"] == 4
    assert len(p1_body["items"]) == 2
    assert len(p2_body["items"]) == 2

    ids = [item["id"] for item in p1_body["items"]] + [
        item["id"] for item in p2_body["items"]
    ]
    assert len(set(ids)) == 4


@pytest.mark.asyncio
async def test_search_rejects_page_over_cap(
    clean_search_tables, clean_es_index,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/decisions",
            json={"page": 101},
        )

    assert response.status_code == 422
    # Best-effort sanity check on the error payload — Pydantic v2 wording
    # for the ``le=100`` constraint may drift across versions, so accept
    # either a mention of the field name or the canonical constraint phrase.
    detail_blob = str(response.json()).lower()
    assert "page" in detail_blob or "less than or equal" in detail_blob


@pytest.mark.asyncio
async def test_search_accepts_page_at_cap(
    clean_search_tables, clean_es_index,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/decisions",
            json={"page": 100, "page_size": 1},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []
