from __future__ import annotations

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, status

from app.core.config import Settings, get_settings
from app.es.client import get_es
from app.modules.search.schemas.search import (
    FacetsRequest,
    FacetsResponse,
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
)
async def search_decisions(
    request: SearchDecisionsRequest,
    es: AsyncElasticsearch = Depends(get_es),
    settings: Settings = Depends(get_settings),
) -> SearchDecisionsResponse:
    service = SearchService(es, index_name=settings.es_court_decisions_index)
    return await service.search(request)


@router.post(
    "/facets",
    response_model=FacetsResponse,
    status_code=status.HTTP_200_OK,
    summary="Aggregations for court decisions (terms + date_histogram)",
    description=(
        "Return facet buckets for the same filter set as `/decisions`: "
        "terms on `court_type`, `dispute_type`, `result`, `region.raw`; "
        "`date_histogram` on `decision_date` by month. "
        "No pagination or sort — aggregations are always top-K."
    ),
)
async def search_decisions_facets(
    request: FacetsRequest,
    es: AsyncElasticsearch = Depends(get_es),
    settings: Settings = Depends(get_settings),
) -> FacetsResponse:
    """Aggregation endpoint paired with `/decisions` for jurimetrics UI."""

    service = SearchService(es, index_name=settings.es_court_decisions_index)
    return await service.facets(request)
