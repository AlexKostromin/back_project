from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DecisionNotFoundError
from app.llm.gateway import LLMGateway
from app.modules.search.repositories.court_decision import CourtDecisionRepository
from app.modules.search.schemas.summary import DecisionSummary


class DecisionSummaryService:
    """Доменный сервис: читает решение из БД, отдаёт текст в LLM-шлюз.

    Сервис намеренно тонкий — вся работа с провайдером (auth,
    truncation, retry, парсинг) живёт в адаптере за ``LLMGateway``.
    Сервис только:

    1. Достаёт ``CourtDecision.full_text`` через репозиторий
       (Postgres — источник истины для текстов решений).
    2. Поднимает 404 ``DecisionNotFoundError``, если id не найден.
    3. Делегирует генерацию шлюзу.

    ``max_input_chars`` принимаем как параметр конструктора, а не
    лезем в ``Settings`` напрямую — это упрощает тестирование и
    оставляет сервис в стороне от глобального конфига.
    """

    def __init__(
        self,
        session: AsyncSession,
        gateway: LLMGateway,
        *,
        max_input_chars: int,
    ) -> None:
        self._repo = CourtDecisionRepository(session)
        self._gateway = gateway
        self._max_input_chars = max_input_chars

    async def summarize(self, decision_id: int) -> DecisionSummary:
        decision = await self._repo.get_by_id(decision_id)
        if decision is None:
            raise DecisionNotFoundError()
        return await self._gateway.summarize(decision.full_text)
