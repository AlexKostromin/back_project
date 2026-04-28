from __future__ import annotations

import structlog

from app.db.models.case import Case
from app.db.repositories.case import CaseRepository
from app.parsers.kad.schemas import KadCaseSummary

logger = structlog.get_logger(__name__)

KAD_SOURCE_NAME = "arbitr"


async def save_case_summary(
    summary: KadCaseSummary,
    repo: CaseRepository,
    *,
    court_tag: str | None = None,
) -> Case:
    """Persist KadCaseSummary as Case row via repository (idempotent upsert).

    court_tag is optional and comes from chronology API (CaseDocumentsPage
    response Items[].CourtTag), not from card HTML. Until Stage 3c.5c
    wires live HTTP, callers pass None and we store NULL — backfilled
    later if needed.

    Args:
        summary: Parsed case summary from card HTML.
        repo: CaseRepository instance bound to active session.
        court_tag: Optional court routing tag from chronology API.

    Returns:
        Persisted Case instance with id and timestamps populated.
    """
    case = _to_case_orm(summary, court_tag=court_tag)
    persisted = await repo.upsert_by_external_id(case)
    logger.info(
        "kad.bridge.case_saved",
        external_id=summary.case_id,
        case_number=summary.case_number,
        instance_level=summary.instance_level,
    )
    return persisted


def _to_case_orm(summary: KadCaseSummary, *, court_tag: str | None) -> Case:
    """Pure mapping function. No I/O. Easy to unit-test.

    Args:
        summary: Parsed case summary from card HTML.
        court_tag: Optional court routing tag.

    Returns:
        Case ORM instance ready for upsert (not yet persisted).
    """
    return Case(
        source_name=KAD_SOURCE_NAME,
        external_id=summary.case_id,
        case_number=summary.case_number,
        court_name=summary.court_name,
        court_type=summary.court_type.value,
        court_tag=court_tag,
        instance_level=summary.instance_level,
        region=summary.region,
        dispute_category=summary.dispute_category,
        parties=[p.model_dump(exclude_none=True) for p in summary.parties],
        judges=list(summary.judges),
        crawled_at=summary.crawled_at,
    )
