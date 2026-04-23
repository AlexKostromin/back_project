from __future__ import annotations

from typing import Any

from elasticsearch import AsyncElasticsearch, BadRequestError

# Name of the primary search index. Tests override this with a random suffix
# so parallel runs don't collide; production code uses the constant directly.
COURT_DECISIONS_INDEX = "court_decisions"


def court_decisions_settings() -> dict[str, Any]:
    """Index-level settings.

    Single shard / single replica is fine for dev and for the MVP scale
    (tens of thousands of documents). Prod will retune — 3–5 shards for
    the hot index, 1 replica minimum for HA.

    Russian analyzer is the built-in one. It stems conservatively and
    lowercases. Richer morphology (e.g. pymorphy, russian_morphology
    plugin) can replace it in a follow-up — the `russian_text` alias
    isolates field mappings from the analyzer choice.
    """

    return {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "analyzer": {
                "russian_text": {
                    "type": "russian",
                },
            },
        },
    }


def court_decisions_mappings() -> dict[str, Any]:
    """Field mappings for ``CourtDecision`` documents.

    Design decisions:

    * Short enum-like fields (``source_name``, ``court_type``,
      ``result``, ``doc_type``, ...) are ``keyword`` — no tokenization,
      exact-match filters, cheap term aggregations for jurimetrics.
    * Long free-form strings (``court_name``, ``region``, ``category``,
      ``full_text``) use ``russian_text`` for full-text search, plus a
      ``.raw`` keyword sub-field for exact-match filters and
      aggregations (`"Арбитражный суд города Москвы"` as one token,
      not seven).
    * Dates use ``date`` so range filters and ``date_histogram``
      aggregations work directly.
    * ``participants`` and ``norms`` are ``nested`` so per-element
      queries don't cross-match across array elements (e.g. "find
      decisions where one participant is plaintiff with INN
      7701234567" can't be cheated by plaintiff matching one element
      and INN another).
    * ``text_hash`` kept as ``keyword`` so we can still dedup at the
      ES layer if we ever need to.
    """

    return {
        "dynamic": "strict",
        "properties": {
            "id": {"type": "long"},
            "source_id": {"type": "keyword"},
            "source_name": {"type": "keyword"},
            "case_number": {"type": "keyword"},
            "court_name": {
                "type": "text",
                "analyzer": "russian_text",
                "fields": {"raw": {"type": "keyword", "ignore_above": 512}},
            },
            "court_type": {"type": "keyword"},
            "instance_level": {"type": "integer"},
            "region": {
                "type": "text",
                "analyzer": "russian_text",
                "fields": {"raw": {"type": "keyword", "ignore_above": 256}},
            },
            "decision_date": {"type": "date"},
            "publication_date": {"type": "date"},
            "doc_type": {"type": "keyword"},
            "judges": {"type": "keyword"},
            "result": {"type": "keyword"},
            "appeal_status": {"type": "keyword"},
            "dispute_type": {"type": "keyword"},
            "category": {
                "type": "text",
                "analyzer": "russian_text",
                "fields": {"raw": {"type": "keyword", "ignore_above": 256}},
            },
            "claim_amount": {"type": "scaled_float", "scaling_factor": 100},
            "full_text": {"type": "text", "analyzer": "russian_text"},
            "text_hash": {"type": "keyword"},
            "source_url": {"type": "keyword", "index": False},
            "minio_path": {"type": "keyword", "index": False},
            "crawled_at": {"type": "date"},
            "parsed_at": {"type": "date"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "participants": {
                "type": "nested",
                "properties": {
                    "name": {
                        "type": "text",
                        "analyzer": "russian_text",
                        "fields": {"raw": {"type": "keyword", "ignore_above": 512}},
                    },
                    "role": {"type": "keyword"},
                    "inn": {"type": "keyword"},
                    "ogrn": {"type": "keyword"},
                },
            },
            "norms": {
                "type": "nested",
                "properties": {
                    "law_name": {
                        "type": "text",
                        "analyzer": "russian_text",
                        "fields": {"raw": {"type": "keyword", "ignore_above": 128}},
                    },
                    "article": {"type": "keyword"},
                    "part": {"type": "keyword"},
                    "paragraph": {"type": "keyword"},
                    "raw_ref": {"type": "text", "analyzer": "russian_text"},
                },
            },
        },
    }


async def ensure_court_decisions_index(
    es: AsyncElasticsearch,
    *,
    name: str = COURT_DECISIONS_INDEX,
) -> bool:
    """Create the ``court_decisions`` index if it does not exist.

    Idempotent: if the index exists already, returns False without
    touching it — we never mutate mappings in place. Migrations of the
    index happen through reindex-to-a-new-name, not through
    ``PUT _mapping`` hacks, because ES rejects most real changes
    anyway (e.g. switching a field from ``text`` to ``keyword``).

    Returns True if the index was freshly created, False if it was
    already there. A concurrent create race (two processes calling
    this at once on first boot) is swallowed — the loser sees
    ``resource_already_exists_exception`` and treats it as "someone
    else got here first".
    """

    body = {
        "settings": court_decisions_settings(),
        "mappings": court_decisions_mappings(),
    }
    try:
        await es.indices.create(index=name, **body)
        return True
    except BadRequestError as exc:
        if exc.meta.status == 400 and "resource_already_exists_exception" in str(exc):
            return False
        raise
