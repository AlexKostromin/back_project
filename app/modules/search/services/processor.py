from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CourtDecision, DecisionNorm, DecisionParticipant
from app.modules.search.repositories.court_decision import CourtDecisionRepository
from app.modules.search.schemas.ingest import IngestResult, IngestStatus
from app.modules.search.schemas.raw_decision import RawDecision

log = structlog.get_logger(__name__)


def compute_text_hash(full_text: str) -> str:
    return hashlib.sha256(full_text.encode("utf-8")).hexdigest()


class DecisionProcessor:
    """Accepts RawDecision from the parser, deduplicates by SHA-256 of full_text,
    and persists to PostgreSQL. ES / Qdrant indexing is a separate step."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CourtDecisionRepository(session)

    async def process(self, raw: RawDecision) -> IngestResult:
        text_hash = compute_text_hash(raw.full_text)

        existing = await self._repo.get_by_text_hash(text_hash)
        if existing is not None:
            log.info(
                "decision.duplicate",
                decision_id=existing.id,
                case_number=raw.case_number,
                text_hash=text_hash,
            )
            return IngestResult(
                status=IngestStatus.DUPLICATE,
                decision_id=existing.id,
                text_hash=text_hash,
            )

        decision = self._to_model(raw, text_hash)
        await self._repo.add(decision)
        await self._session.commit()

        log.info(
            "decision.created",
            decision_id=decision.id,
            case_number=raw.case_number,
            source=raw.source_name.value,
        )
        return IngestResult(
            status=IngestStatus.CREATED,
            decision_id=decision.id,
            text_hash=text_hash,
        )

    @staticmethod
    def _to_model(raw: RawDecision, text_hash: str) -> CourtDecision:
        return CourtDecision(
            source_id=raw.source_id,
            source_name=raw.source_name.value,
            case_number=raw.case_number,
            court_name=raw.court_name,
            court_type=raw.court_type.value,
            instance_level=raw.instance_level if raw.instance_level is not None else 1,
            region=raw.region,
            decision_date=raw.decision_date,
            publication_date=raw.publication_date,
            doc_type=raw.doc_type.value,
            judges=list(raw.judges),
            result=raw.result.value if raw.result else "other",
            appeal_status=raw.appeal_status.value if raw.appeal_status else "none",
            dispute_type=raw.dispute_type.value if raw.dispute_type else "civil",
            category=raw.category,
            claim_amount=raw.claim_amount,
            full_text=raw.full_text,
            sections=raw.sections.model_dump() if raw.sections else None,
            text_hash=text_hash,
            source_url=str(raw.source_url),
            crawled_at=datetime.now(timezone.utc),
            parsed_at=datetime.now(timezone.utc),
            participants=[
                DecisionParticipant(
                    name=p.name,
                    role=p.role.value,
                    inn=p.inn,
                    ogrn=p.ogrn,
                )
                for p in raw.participants
            ],
            norms=[
                DecisionNorm(
                    law_name=n.law_name,
                    article=n.article,
                    part=n.part,
                    paragraph=n.paragraph,
                    raw_ref=n.raw_ref,
                )
                for n in raw.norms
            ],
        )
