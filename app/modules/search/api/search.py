from __future__ import annotations

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, status

from app.core.config import Settings, get_settings
from app.es.client import get_es
from app.modules.search.schemas.search import (
    SearchDecisionsRequest,
    SearchDecisionsResponse,
)
from app.modules.search.services.search import SearchService

router = APIRouter(prefix="/decisions", tags=["search:decisions"])


@router.post(
    "",
    response_model=SearchDecisionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Full-text + filter search over Elasticsearch",
    description=(
        "Run a bool-query against Elasticsearch: `multi_match` on "
        "`full_text`/`court_name`/`category` with Russian analyzer when "
        "`query` is set; `term`/`range` filters for enums and ranges. "
        "Snippets come from ES highlight, falling back to the first 300 "
        "chars of `full_text` on filter-only requests. "
        "`sort_by=relevance` requires a `query`; deep pagination is "
        "capped at page=100 (see schema)."
    ),
)
async def search_decisions(
    request: SearchDecisionsRequest,
    es: AsyncElasticsearch = Depends(get_es),
    settings: Settings = Depends(get_settings),
) -> SearchDecisionsResponse:
    """Search court decisions over Elasticsearch.

    See the request schema examples for common patterns: filter-only,
    relevance, court+period narrowing, and query+filters combined.
    """
    service = SearchService(es, index_name=settings.es_court_decisions_index)
    return await service.search(request)
