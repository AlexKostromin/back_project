from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.search.schemas.ingest import IngestResult
from app.modules.search.schemas.raw_decision import RawDecision
from app.modules.search.services.processor import DecisionProcessor

router = APIRouter(prefix="/ingest", tags=["search:ingest"])


@router.post(
    "/decision",
    response_model=IngestResult,
    status_code=status.HTTP_200_OK,
    summary="Ingest a single RawDecision from the parser",
)
async def ingest_decision(
    raw: RawDecision,
    session: AsyncSession = Depends(get_session),
) -> IngestResult:
    processor = DecisionProcessor(session)
    return await processor.process(raw)
