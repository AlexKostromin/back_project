from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Case


class CaseRepository:
    """PostgreSQL access for :class:`Case`.

    Provides idempotent upsert by (source_name, external_id) to support
    re-parsing case cards when updated on the source site (e.g., new judge
    assigned, party added). Cases are the source of truth for case-level
    metadata; :class:`CourtDecision` rows link via FK.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: int) -> Case | None:
        """Fetch a case by its primary key.

        Args:
            id: Primary key of the case.

        Returns:
            The case if found, otherwise None.
        """
        stmt = select(Case).where(Case.id == id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_external_id(
        self, source_name: str, external_id: str
    ) -> Case | None:
        """Fetch a case by its source + external ID.

        Args:
            source_name: Parser source name (e.g., 'arbitr').
            external_id: External case ID from source (e.g., KAD UUID).

        Returns:
            The case if found, otherwise None.
        """
        stmt = select(Case).where(
            Case.source_name == source_name,
            Case.external_id == external_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_by_external_id(self, case: Case) -> Case:
        """Insert or update a case by (source_name, external_id).

        Idempotent operation using PostgreSQL INSERT ... ON CONFLICT DO UPDATE.
        If a case with the same (source_name, external_id) exists, updates all
        fields except id, created_at. If not found, inserts a new row.

        Args:
            case: Case instance to upsert (id is ignored if present).

        Returns:
            The persisted case with id and timestamps populated.
        """
        # Prepare values for insert/update (exclude id, created_at for update)
        values = {
            "source_name": case.source_name,
            "external_id": case.external_id,
            "case_number": case.case_number,
            "court_name": case.court_name,
            "court_type": case.court_type,
            "court_tag": case.court_tag,
            "instance_level": case.instance_level,
            "region": case.region,
            "dispute_category": case.dispute_category,
            "parties": case.parties,
            "judges": case.judges,
            "crawled_at": case.crawled_at,
        }

        stmt = insert(Case).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_cases_source_external_id",
            set_={
                "case_number": stmt.excluded.case_number,
                "court_name": stmt.excluded.court_name,
                "court_type": stmt.excluded.court_type,
                "court_tag": stmt.excluded.court_tag,
                "instance_level": stmt.excluded.instance_level,
                "region": stmt.excluded.region,
                "dispute_category": stmt.excluded.dispute_category,
                "parties": stmt.excluded.parties,
                "judges": stmt.excluded.judges,
                "crawled_at": stmt.excluded.crawled_at,
                # updated_at is auto-updated by onupdate=func.now()
            },
        )
        stmt = stmt.returning(Case)

        result = await self._session.execute(stmt)
        persisted = result.scalar_one()

        # Expire to ensure fresh load from DB on next access (includes updated_at)
        await self._session.refresh(persisted)
        await self._session.flush()

        return persisted

    MAX_LIST_LIMIT = 1000

    async def list_by_court_tag(
        self, court_tag: str, limit: int = 100, offset: int = 0
    ) -> list[Case]:
        """List cases by court_tag with pagination.

        Used for future jurimetric facets (e.g., "show all cases from SEVASTOPOL").

        Args:
            court_tag: Court routing tag to filter by.
            limit: Maximum number of results (default 100, capped at MAX_LIST_LIMIT).
            offset: Number of results to skip (default 0).

        Returns:
            List of matching cases ordered by id (chronological).
        """
        if limit < 0 or offset < 0:
            raise ValueError("limit and offset must be non-negative")
        effective_limit = min(limit, self.MAX_LIST_LIMIT)
        stmt = (
            select(Case)
            .where(Case.court_tag == court_tag)
            .order_by(Case.id)
            .limit(effective_limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
