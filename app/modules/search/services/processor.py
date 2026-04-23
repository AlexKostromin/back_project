from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import structlog
from elasticsearch import AsyncElasticsearch
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
    persists to PostgreSQL, and index the document in Elasticsearch.

    ES indexing is best-effort: Postgres is the source of truth, so if ES is
    down the ingest still returns CREATED with ``es_indexed=False`` left on
    the row. A future reindex task will pick up documents with
    ``es_indexed=False`` and finish the job. This keeps ingest resilient
    during ES restarts without dropping data.
    """

    def __init__(
        self,
        session: AsyncSession,
        es: AsyncElasticsearch,
        *,
        index_name: str,
    ) -> None:
        self._session = session
        self._es = es
        self._index_name = index_name
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

        # Secondary index. Failures are logged and swallowed; es_indexed
        # stays False so a future reindex pass can retry.
        try:
            await self._index_in_es(decision)
            decision.es_indexed = True
            await self._session.commit()
        except Exception as exc:  # noqa: BLE001 — isolating ES from PG write path
            log.warning(
                "decision.es_index_failed",
                decision_id=decision.id,
                error=str(exc),
            )

        return IngestResult(
            status=IngestStatus.CREATED,
            decision_id=decision.id,
            text_hash=text_hash,
        )

    async def _index_in_es(self, decision: CourtDecision) -> None:
        await self._es.index(
            index=self._index_name,
            id=str(decision.id),
            document=self._serialize(decision),
            # wait_for so the doc is searchable by the time we return. Cheap
            # for a single ingest; we'll switch to async refresh once bulk
            # indexing lands.
            refresh="wait_for",
        )

    @staticmethod
    def _serialize(decision: CourtDecision) -> dict[str, Any]:
        return {
            "id": decision.id,
            "source_id": decision.source_id,
            "source_name": decision.source_name,
            "case_number": decision.case_number,
            "court_name": decision.court_name,
            "court_type": decision.court_type,
            "instance_level": decision.instance_level,
            "region": decision.region,
            "decision_date": decision.decision_date.isoformat(),
            "publication_date": (
                decision.publication_date.isoformat()
                if decision.publication_date is not None
                else None
            ),
            "doc_type": decision.doc_type,
            "judges": list(decision.judges),
            "result": decision.result,
            "appeal_status": decision.appeal_status,
            "dispute_type": decision.dispute_type,
            "category": decision.category,
            "claim_amount": (
                float(decision.claim_amount)
                if decision.claim_amount is not None
                else None
            ),
            "full_text": decision.full_text,
            "text_hash": decision.text_hash,
            "source_url": decision.source_url,
            "minio_path": decision.minio_path,
            "crawled_at": decision.crawled_at.isoformat(),
            "parsed_at": decision.parsed_at.isoformat(),
            "created_at": decision.created_at.isoformat(),
            "updated_at": decision.updated_at.isoformat(),
            "participants": [
                {
                    "name": p.name,
                    "role": p.role,
                    "inn": p.inn,
                    "ogrn": p.ogrn,
                }
                for p in decision.participants
            ],
            "norms": [
                {
                    "law_name": n.law_name,
                    "article": n.article,
                    "part": n.part,
                    "paragraph": n.paragraph,
                    "raw_ref": n.raw_ref,
                }
                for n in decision.norms
            ],
        }

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
