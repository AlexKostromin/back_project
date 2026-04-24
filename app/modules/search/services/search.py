from __future__ import annotations

from elasticsearch import AsyncElasticsearch

from app.modules.search.repositories.es_court_decision import (
    EsCourtDecisionRepository,
)
from app.modules.search.schemas.search import (
    FacetsRequest,
    FacetsResponse,
    SearchDecisionsRequest,
    SearchDecisionsResponse,
)


class SearchService:
    """Elasticsearch-backed decisions search.

    Thin orchestration layer: takes a validated request, delegates the
    actual query construction and hit mapping to
    :class:`EsCourtDecisionRepository`, and wraps the result in a
    paginated response envelope. Keeps the route handler free of any
    ES-specific wiring.
    """

    def __init__(self, es: AsyncElasticsearch, *, index_name: str) -> None:
        self._repo = EsCourtDecisionRepository(es, index_name=index_name)

    async def search(
        self, request: SearchDecisionsRequest
    ) -> SearchDecisionsResponse:
        items, total = await self._repo.search(request)
        return SearchDecisionsResponse(
            total=total,
            page=request.page,
            page_size=request.page_size,
            items=items,
        )

    async def facets(self, request: FacetsRequest) -> FacetsResponse:
        return await self._repo.facets(request)
