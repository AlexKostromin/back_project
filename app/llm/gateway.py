from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.search.schemas.summary import DecisionSummary


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
