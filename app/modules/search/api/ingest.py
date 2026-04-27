from __future__ import annotations

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.es.client import get_es
from app.modules.search.schemas.ingest import IngestResult
from app.modules.search.schemas.raw_decision import RawDecision
from app.modules.search.services.processor import DecisionProcessor

router = APIRouter(prefix="/ingest", tags=["search:ingest"])


@router.post(
    "/decision",
    response_model=IngestResult,
    status_code=status.HTTP_200_OK,
    summary="Приём одного RawDecision от парсера",
)
async def ingest_decision(
    raw: RawDecision,
    session: AsyncSession = Depends(get_session),
    es: AsyncElasticsearch = Depends(get_es),
    settings: Settings = Depends(get_settings),
) -> IngestResult:
    """Принимает разобранное решение от парсера и сохраняет его в БД и ES."""
    processor = DecisionProcessor(
        session,
        es,
        index_name=settings.es_court_decisions_index,
    )
    return await processor.process(raw)
