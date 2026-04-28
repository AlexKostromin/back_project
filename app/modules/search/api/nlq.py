from __future__ import annotations

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, status

from app.core.config import Settings, get_settings
from app.es.client import get_es
from app.llm.dependencies import get_llm_gateway
from app.llm.gateway import LLMGateway
from app.modules.search.schemas.nlq import NLQRequest, NLQResponse
from app.modules.search.services.nlq import NLQService
from app.modules.search.services.search import SearchService

router = APIRouter(prefix="/decisions", tags=["search:decisions"])


@router.post(
    "/nlq",
    response_model=NLQResponse,
    status_code=status.HTTP_200_OK,
    summary="Поиск решений по натуральному запросу через LLM",
    description=(
        "Принимает натуральный текст вида «налоговые споры в Москве "
        "за 2025», переводит его через GigaChat в структурный "
        "SearchDecisionsRequest и сразу возвращает результаты поиска. "
        "В ответе — что LLM поняла (parsed_query, можно показать "
        "пользователю и дать ему поправить) и сами результаты "
        "(контракт совпадает с POST /decisions)."
    ),
)
async def nlq_search(
    request: NLQRequest,
    es: AsyncElasticsearch = Depends(get_es),
    settings: Settings = Depends(get_settings),
    gateway: LLMGateway = Depends(get_llm_gateway),
) -> NLQResponse:
    """Натурально-языковой поиск судебных решений."""

    search_service = SearchService(
        es, index_name=settings.es_court_decisions_index
    )
    nlq_service = NLQService(gateway, search_service)
    return await nlq_service.query(request.text)
