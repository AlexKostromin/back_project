from __future__ import annotations

from app.llm.gateway import LLMGateway
from app.modules.search.schemas.nlq import NLQResponse
from app.modules.search.services.search import SearchService


class NLQService:
    """Оркестратор NLQ: LLM-парсер + существующий SearchService.

    Сервис намеренно тонкий: gateway отвечает за натуральный язык →
    структурный запрос (с собственными degraded-стратегиями), а
    :class:`SearchService` уже умеет выполнять поиск по этому запросу.
    Сам сервис только склеивает их и собирает ответ — никакой
    параллельной бизнес-логики, которая могла бы расходиться с
    обычным ``POST /decisions``.
    """

    def __init__(self, gateway: LLMGateway, search: SearchService) -> None:
        self._gateway = gateway
        self._search = search

    async def query(self, text: str) -> NLQResponse:
        """Распарсить ``text`` через LLM и сразу выполнить поиск."""

        parsed, tokens = await self._gateway.parse_search_query(text)
        results = await self._search.search(parsed)
        return NLQResponse(
            parsed_query=parsed,
            results=results,
            tokens_used=tokens,
        )
