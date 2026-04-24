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
)
async def search_decisions(
    request: SearchDecisionsRequest,
    es: AsyncElasticsearch = Depends(get_es),
    settings: Settings = Depends(get_settings),
) -> SearchDecisionsResponse:
    service = SearchService(es, index_name=settings.es_court_decisions_index)
    return await service.search(request)
