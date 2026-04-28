from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.modules.search.schemas.summary import DecisionSummary

if TYPE_CHECKING:
    # Локальный импорт под TYPE_CHECKING: схема ``SearchDecisionsRequest``
    # лежит в search-модуле, а сам gateway — общий слой ``app.llm``.
    # Прямой импорт не порождает циклов сейчас, но связывает чистый
    # шлюз с конкретным доменом раньше времени; держим связь только
    # на типовом уровне.
    from app.modules.search.schemas.search import SearchDecisionsRequest


class LLMGateway(ABC):
    """Абстрактный шлюз к LLM-провайдеру.

    Сервисный слой LexInsight зависит только от этого интерфейса —
    конкретный адаптер (GigaChat сейчас, YandexGPT/Claude позже)
    подменяется на DI-уровне. Это даёт три эффекта:

    1. Тесты: подменяем адаптер фейком, не дёргая реальный API.
    2. Fallback chain (см. CLAUDE.md "LLM Gateway"): обвязка над
       несколькими адаптерами реализуется снаружи без правки сервисов.
    3. 152-ФЗ: какие именно провайдеры вызываются — решается на
       уровне сборки приложения, а не размазано по бизнес-логике.
    """

    @abstractmethod
    async def summarize(self, text: str) -> DecisionSummary:
        """Сгенерировать структурированное саммари судебного решения.

        Args:
            text: полный текст решения. Адаптер сам отвечает за
                truncation под context window своей модели — сервису
                не нужно знать лимиты конкретного провайдера.

        Returns:
            ``DecisionSummary`` с заполненными полями.

        Raises:
            LLMError: любой сбой провайдера (auth/rate/timeout/контракт).
        """

    @abstractmethod
    async def parse_search_query(
        self, text: str
    ) -> tuple[SearchDecisionsRequest, int]:
        """Перевести натуральный запрос в структурный SearchDecisionsRequest.

        Args:
            text: пользовательская фраза (натуральный язык).
                Адаптер сам отвечает за truncation/защиту входа.

        Returns:
            ``(parsed_request, tokens_used)``. ``tokens_used`` отдаётся
            отдельно, чтобы ``NLQResponse`` мог положить его в ответ —
            gateway не должен конструировать сам Response.

        Raises:
            LLMError: при auth/rate/timeout/контракте провайдера.
                НИКОГДА не raise при «LLM понял частично»: в этом случае
                возвращаем degraded-парсинг (минимум —
                ``query=text``, ``sort_by=DATE_DESC``).
        """
