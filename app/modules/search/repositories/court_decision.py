from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CourtDecision


class CourtDecisionRepository:
    """PostgreSQL access for :class:`CourtDecision`.

    Kept narrow on purpose: the read list-path moved to Elasticsearch
    (see :class:`EsCourtDecisionRepository`), so this repo only covers
    the write/ingest path (dedup by text hash, insert) and the
    single-document read-one path used by the decision detail route.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_text_hash(self, text_hash: str) -> CourtDecision | None:
        stmt = select(CourtDecision).where(CourtDecision.text_hash == text_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, decision_id: int) -> CourtDecision | None:
        stmt = select(CourtDecision).where(CourtDecision.id == decision_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def add(self, decision: CourtDecision) -> CourtDecision:
        self._session.add(decision)
        await self._session.flush()
        return decision
