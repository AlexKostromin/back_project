from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import structlog
from elasticsearch import AsyncElasticsearch

from app.modules.search.schemas.enums import SortBy
from app.modules.search.schemas.search import (
    DecisionListItem,
    SearchDecisionsRequest,
)

log = structlog.get_logger(__name__)

# Fallback snippet length when ES returns no highlight fragment (e.g. a
# filter-only query with no ``query`` term, or a text match that didn't
# land in ``full_text``). Matches the previous SQL-path behaviour so
# clients don't see a sudden preview-size change.
SNIPPET_LEN = 300

# Fields loaded from ``_source``. full_text is included so we can build
# a fallback snippet when highlight is absent; everything else is what
# DecisionListItem needs directly.
_SOURCE_FIELDS = [
    "id",
    "case_number",
    "court_name",
    "court_type",
    "region",
    "decision_date",
    "doc_type",
    "result",
    "appeal_status",
    "dispute_type",
    "claim_amount",
    "full_text",
]


class EsCourtDecisionRepository:
    """Elasticsearch-backed read path for court decisions.

    Builds a ``bool`` query (must = text match or match_all, filter =
    exact/range predicates), applies sort + pagination, and requests a
    plain-text highlight on ``full_text`` for the snippet. Only fields
    needed by ``DecisionListItem`` are pulled via ``_source``.
    """

    def __init__(self, es: AsyncElasticsearch, *, index_name: str) -> None:
        self._es = es
        self._index_name = index_name

    async def search(
        self, request: SearchDecisionsRequest
    ) -> tuple[list[DecisionListItem], int]:
        body = self._build_body(request)

        log.info(
            "search.decisions.es_query",
            index=self._index_name,
            has_query=request.query is not None,
            page=request.page,
            page_size=request.page_size,
            sort_by=request.sort_by.value,
        )

        resp = await self._es.search(index=self._index_name, body=body)

        total = int(resp["hits"]["total"]["value"])
        items = [self._hit_to_item(hit) for hit in resp["hits"]["hits"]]
        return items, total

    def _build_body(self, request: SearchDecisionsRequest) -> dict[str, Any]:
        if request.query is not None:
            must: dict[str, Any] = {
                "multi_match": {
                    "query": request.query,
                    "fields": [
                        "full_text",
                        "court_name^2",
                        "category^1.5",
                    ],
                    "type": "best_fields",
                }
            }
        else:
            must = {"match_all": {}}

        filters = self._build_filters(request)
        sort = self._build_sort(request.sort_by)

        return {
            "query": {"bool": {"must": [must], "filter": filters}},
            "sort": sort,
            "from": (request.page - 1) * request.page_size,
            "size": request.page_size,
            "track_total_hits": True,
            "highlight": {
                "fields": {
                    "full_text": {
                        "fragment_size": 300,
                        "number_of_fragments": 1,
                        "no_match_size": 0,
                    }
                },
                "pre_tags": [""],
                "post_tags": [""],
            },
            "_source": _SOURCE_FIELDS,
        }

    @staticmethod
    def _build_filters(request: SearchDecisionsRequest) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = []

        if request.case_number is not None:
            filters.append({"term": {"case_number": request.case_number}})
        if request.court_type is not None:
            filters.append({"term": {"court_type": request.court_type.value}})
        if request.region is not None:
            # ``region`` is a text field with a ``.raw`` keyword sub-field;
            # filter against the keyword so "Москва" doesn't fan out into
            # tokens.
            filters.append({"term": {"region.raw": request.region}})
        if request.doc_type is not None:
            filters.append({"term": {"doc_type": request.doc_type.value}})
        if request.result is not None:
            filters.append({"term": {"result": request.result.value}})
        if request.appeal_status is not None:
            filters.append({"term": {"appeal_status": request.appeal_status.value}})
        if request.dispute_type is not None:
            filters.append({"term": {"dispute_type": request.dispute_type.value}})

        date_range: dict[str, str] = {}
        if request.date_from is not None:
            date_range["gte"] = request.date_from.isoformat()
        if request.date_to is not None:
            date_range["lte"] = request.date_to.isoformat()
        if date_range:
            filters.append({"range": {"decision_date": date_range}})

        amount_range: dict[str, float] = {}
        if request.claim_amount_min is not None:
            amount_range["gte"] = float(request.claim_amount_min)
        if request.claim_amount_max is not None:
            amount_range["lte"] = float(request.claim_amount_max)
        if amount_range:
            filters.append({"range": {"claim_amount": amount_range}})

        return filters

    @staticmethod
    def _build_sort(sort_by: SortBy) -> list[dict[str, str]]:
        if sort_by is SortBy.DATE_ASC:
            return [{"decision_date": "asc"}, {"id": "asc"}]
        return [{"decision_date": "desc"}, {"id": "desc"}]

    @staticmethod
    def _hit_to_item(hit: dict[str, Any]) -> DecisionListItem:
        src = hit["_source"]
        highlight_fragments = hit.get("highlight", {}).get("full_text", [])
        if highlight_fragments:
            snippet = highlight_fragments[0]
        else:
            snippet = src["full_text"][:SNIPPET_LEN]

        claim_amount_raw = src.get("claim_amount")
        claim_amount = (
            Decimal(str(claim_amount_raw)) if claim_amount_raw is not None else None
        )

        return DecisionListItem(
            id=int(src["id"]),
            case_number=src["case_number"],
            court_name=src["court_name"],
            court_type=src["court_type"],
            region=src.get("region"),
            decision_date=date.fromisoformat(src["decision_date"]),
            doc_type=src["doc_type"],
            result=src.get("result"),
            appeal_status=src.get("appeal_status"),
            dispute_type=src.get("dispute_type"),
            claim_amount=claim_amount,
            snippet=snippet,
        )
