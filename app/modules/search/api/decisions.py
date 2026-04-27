from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.search.schemas.decision import DecisionResponse
from app.modules.search.services.decision import DecisionService

router = APIRouter(prefix="/decisions", tags=["search:decisions"])


@router.get(
    "/{decision_id}",
    response_model=DecisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Карточка судебного решения по id с участниками и нормами",
)
async def get_decision(
    decision_id: int,
    session: AsyncSession = Depends(get_session),
) -> DecisionResponse:
    """Возвращает полную карточку решения: метаданные, участников и нормы."""
    service = DecisionService(session)
    return await service.get(decision_id)
