from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

    async def iter_unindexed(
        self, *, batch_size: int = 100
    ) -> AsyncIterator[Sequence[CourtDecision]]:
        """Yield batches of ``CourtDecision`` rows where ``es_indexed=False``.

        Eager-loads ``participants`` and ``norms`` via ``selectinload`` so
        callers can serialize without N+1 hits back to the DB. Uses keyset
        pagination on ``id`` — OFFSET would degrade to O(N^2) on large
        tables; a cursor on an indexed monotonically-growing PK is stable
        and cheap.
        """

        async for batch in self._iter_batches(
            batch_size=batch_size,
            only_unindexed=True,
        ):
            yield batch

    async def iter_all(
        self, *, batch_size: int = 100
    ) -> AsyncIterator[Sequence[CourtDecision]]:
        """Yield every ``CourtDecision`` in id order, batched.

        Used by ``--all`` reindex after a mapping change (where the
        index is rebuilt under a new name and we need to repopulate
        from Postgres, the source of truth).
        """

        async for batch in self._iter_batches(
            batch_size=batch_size,
            only_unindexed=False,
        ):
            yield batch

    async def _iter_batches(
        self,
        *,
        batch_size: int,
        only_unindexed: bool,
    ) -> AsyncIterator[Sequence[CourtDecision]]:
        last_id = 0
        while True:
            stmt = (
                select(CourtDecision)
                .options(
                    selectinload(CourtDecision.participants),
                    selectinload(CourtDecision.norms),
                )
                .where(CourtDecision.id > last_id)
                .order_by(CourtDecision.id)
                .limit(batch_size)
            )
            if only_unindexed:
                stmt = stmt.where(CourtDecision.es_indexed.is_(False))

            result = await self._session.execute(stmt)
            batch = result.scalars().all()
            if not batch:
                return

            yield batch
            last_id = batch[-1].id

    async def mark_indexed(self, decision_ids: Sequence[int]) -> None:
        """Bulk-update ``es_indexed=True`` for given ids. Caller commits."""

        if not decision_ids:
            return
        stmt = (
            update(CourtDecision)
            .where(CourtDecision.id.in_(decision_ids))
            .values(es_indexed=True)
        )
        await self._session.execute(stmt)
