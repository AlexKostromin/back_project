from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DecisionNotFoundError
from app.modules.search.repositories.court_decision import CourtDecisionRepository
from app.modules.search.schemas.decision import DecisionResponse


class DecisionService:
    """Read-side service for court decisions.

    Responsible for loading a decision with its related participants and norms
    and translating it into the API response schema. Raises
    ``DecisionNotFoundError`` when the decision does not exist.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._repo = CourtDecisionRepository(session)

    async def get(self, decision_id: int) -> DecisionResponse:
        decision = await self._repo.get_by_id(decision_id)
        if decision is None:
            raise DecisionNotFoundError()
        return DecisionResponse.model_validate(decision)
