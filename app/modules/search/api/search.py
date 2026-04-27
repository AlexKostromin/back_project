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
    summary="Полнотекстовый поиск и фильтрация по Elasticsearch",
    description=(
        "Выполняет bool-запрос к Elasticsearch: `multi_match` по "
        "`full_text`/`court_name`/`category` с русским анализатором, "
        "когда задан `query`; `term`/`range` фильтры для enum-ов и "
        "диапазонов. Snippet берётся из ES highlight, а для запросов "
        "только по фильтрам — из первых 300 символов `full_text`. "
        "`sort_by=relevance` требует непустой `query`; глубокая "
        "пагинация ограничена `page=100` (см. схему)."
    ),
)
async def search_decisions(
    request: SearchDecisionsRequest,
    es: AsyncElasticsearch = Depends(get_es),
    settings: Settings = Depends(get_settings),
) -> SearchDecisionsResponse:
    """Поиск судебных решений через Elasticsearch.

    Типичные сценарии смотрите в примерах схемы запроса: только
    фильтры, поиск по релевантности, сужение по суду и периоду, а
    также комбинация полнотекстового запроса и фильтров.
    """
    service = SearchService(es, index_name=settings.es_court_decisions_index)
    return await service.search(request)


@router.post(
    "/facets",
    response_model=FacetsResponse,
    status_code=status.HTTP_200_OK,
    summary="Агрегации по судебным решениям (terms + date_histogram)",
    description=(
        "Возвращает facet-бакеты для того же набора фильтров, что и "
        "`/decisions`: terms по `court_type`, `dispute_type`, `result`, "
        "`region.raw`; `date_histogram` по `decision_date` с шагом "
        "в месяц. Пагинации и сортировки нет — агрегации всегда "
        "возвращают top-K."
    ),
)
async def search_decisions_facets(
    request: FacetsRequest,
    es: AsyncElasticsearch = Depends(get_es),
    settings: Settings = Depends(get_settings),
) -> FacetsResponse:
    """Эндпойнт агрегаций, парный к `/decisions`, для UI юриметрии."""

    service = SearchService(es, index_name=settings.es_court_decisions_index)
    return await service.facets(request)
