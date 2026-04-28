from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rate_limit import _per_minute_limit, llm_limiter
from app.db.session import get_session
from app.llm.dependencies import get_llm_gateway
from app.llm.gateway import LLMGateway
from app.modules.search.schemas.summary import DecisionSummary
from app.modules.search.services.summary import DecisionSummaryService

router = APIRouter(prefix="/decisions", tags=["search:decisions"])


@router.post(
    "/{decision_id}/summary",
    response_model=DecisionSummary,
    status_code=status.HTTP_200_OK,
    summary="Краткое саммари судебного решения через LLM",
    description=(
        "Загружает текст решения из БД и отдаёт его в GigaChat-Lite "
        "для генерации структурированного саммари: суть спора, "
        "стороны, применённые нормы, итог суда. Текст обрезается "
        "до лимита ``gigachat_max_input_chars`` (по умолчанию ~24K "
        "символов), чтобы поместиться в context window модели Lite. "
        "Если решение не найдено — 404; если LLM недоступна — 502/503/504; "
        "если IP превысил per-minute лимит — 429 с ``Retry-After``."
    ),
)
@llm_limiter.limit(_per_minute_limit)
async def get_decision_summary(
    request: Request,  # обязателен для slowapi — из него берётся IP
    decision_id: int,
    session: AsyncSession = Depends(get_session),
    gateway: LLMGateway = Depends(get_llm_gateway),
    settings: Settings = Depends(get_settings),
) -> DecisionSummary:
    """Сгенерировать саммари судебного решения по его id."""

    service = DecisionSummaryService(
        session,
        gateway,
        max_input_chars=settings.gigachat_max_input_chars,
    )
    return await service.summarize(decision_id)
