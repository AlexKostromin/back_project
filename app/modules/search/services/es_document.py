from __future__ import annotations

from typing import Any

from app.db.models import CourtDecision


def serialize_decision(decision: CourtDecision) -> dict[str, Any]:
    """Map a persisted ``CourtDecision`` aggregate to the ES document shape.

    Used by the ingest dual-write path and by the reindex backfill script
    so both produce the same shape — otherwise documents indexed by one
    path and re-indexed by the other would drift over time.

    Expects ``participants`` and ``norms`` relationships to be loaded;
    callers are responsible for eager-loading them (selectinload /
    joinedload) to avoid N+1.
    """

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
