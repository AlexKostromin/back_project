"""Tests for the search-reindex slice.

Covers:
* ``CourtDecisionRepository.iter_unindexed`` — keyset-batched, filters by
  ``es_indexed=False``, eager-loads relations.
* ``CourtDecisionRepository.iter_all`` — keyset-batched over every row.
* ``CourtDecisionRepository.mark_indexed`` — bulk flag flip.
* ``scripts/reindex_es._run`` — default backfill, ``--all`` rebuild,
  ``--dry-run`` (no writes).

The reindex script reads ``get_settings().es_court_decisions_index``
directly (not via ``Depends``), so we route it to the test index by
patching ``reindex_es.get_settings`` rather than via FastAPI's dependency
override system.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import Settings
from app.db import session as db_session
from app.db.models import CourtDecision, DecisionNorm, DecisionParticipant
from app.es import client as es_client
from scripts import reindex_es
from tests.conftest import TEST_ES_INDEX


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decision(
    *,
    case_number: str,
    text_hash: str,
    es_indexed: bool = False,
    full_text: str = "текст решения",
) -> CourtDecision:
    """Build a minimal CourtDecision with one participant + one norm.

    Constructed directly (not via DecisionProcessor) so tests stay fast
    and don't depend on the ingest endpoint. Mirrors the field set
    required by ``serialize_decision`` so the reindex script can map
    it to ES without KeyError.
    """

    now = datetime.now(timezone.utc)
    return CourtDecision(
        source_id=f"src-{case_number}",
        source_name="arbitr",
        case_number=case_number,
        court_name="Арбитражный суд города Москвы",
        court_type="arbitrazh",
        instance_level=1,
        region="Москва",
        decision_date=date(2025, 6, 1),
        publication_date=date(2025, 6, 5),
        doc_type="решение",
        judges=["Иванов И.И."],
        result="satisfied",
        appeal_status="none",
        dispute_type="civil",
        category="Поставка",
        claim_amount=Decimal("100000.00"),
        full_text=full_text,
        sections=None,
        text_hash=text_hash,
        source_url="https://kad.arbitr.ru/Card/xxx",
        crawled_at=now,
        parsed_at=now,
        es_indexed=es_indexed,
        participants=[
            DecisionParticipant(
                name="ООО Ромашка", role="plaintiff", inn="7701234567", ogrn=None
            ),
        ],
        norms=[
            DecisionNorm(
                law_name="ГК РФ",
                article="506",
                part=None,
                paragraph=None,
                raw_ref="ст. 506 ГК РФ",
            ),
        ],
    )


async def _seed(decisions: list[CourtDecision]) -> list[int]:
    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        for d in decisions:
            session.add(d)
        await session.commit()
        return [d.id for d in decisions]


@pytest_asyncio.fixture
async def reindex_test_index(monkeypatch):
    """Point ``scripts.reindex_es`` at the test ES index.

    The script imports ``get_settings`` at module load and calls it
    inside ``_run``; patching the bound name in the script's namespace
    is the cleanest override (no need to clear ``lru_cache`` or fight
    pydantic-settings env precedence).

    Index lifecycle (delete + recreate fresh, drop on teardown) is
    handled by the ``clean_es_index`` fixture — depend on both.
    """

    test_settings = Settings(es_court_decisions_index=TEST_ES_INDEX)
    monkeypatch.setattr(reindex_es, "get_settings", lambda: test_settings)
    yield test_settings


def _ns(**overrides) -> argparse.Namespace:
    """Build the argparse.Namespace _run expects.

    Mirrors the four flags exposed by the CLI parser so tests don't
    silently drift if a new flag is added without updating defaults.
    """

    defaults = {"batch_size": 100, "dry_run": False, "all": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_iter_unindexed_yields_only_unindexed_rows_in_id_order(
    clean_search_tables,
):
    from app.modules.search.repositories.court_decision import (
        CourtDecisionRepository,
    )

    ids = await _seed(
        [
            _make_decision(case_number="A-1", text_hash="h" * 64, es_indexed=False),
            _make_decision(
                case_number="A-2", text_hash="h" * 63 + "a", es_indexed=True
            ),
            _make_decision(
                case_number="A-3", text_hash="h" * 63 + "b", es_indexed=False
            ),
        ]
    )

    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        repo = CourtDecisionRepository(session)
        seen: list[int] = []
        async for batch in repo.iter_unindexed(batch_size=100):
            seen.extend(d.id for d in batch)

    # Only the two es_indexed=False rows; in ascending id order.
    assert seen == [ids[0], ids[2]]


@pytest.mark.asyncio
async def test_iter_unindexed_batches_by_size(clean_search_tables):
    from app.modules.search.repositories.court_decision import (
        CourtDecisionRepository,
    )

    await _seed(
        [
            _make_decision(case_number=f"A-{i}", text_hash=f"{i:064x}")
            for i in range(5)
        ]
    )

    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        repo = CourtDecisionRepository(session)
        sizes = []
        async for batch in repo.iter_unindexed(batch_size=2):
            sizes.append(len(batch))

    # 5 rows / batch_size=2 → keyset pagination yields 2 + 2 + 1.
    assert sizes == [2, 2, 1]


@pytest.mark.asyncio
async def test_iter_unindexed_eager_loads_relationships(clean_search_tables):
    """selectinload should hydrate participants/norms in the same trip;
    accessing them after the session is closed must not raise.

    With ``expire_on_commit=False`` the loaded collections survive
    session close — but only if they were eager-loaded. If selectinload
    is removed, this test would break with DetachedInstanceError on
    attribute access.
    """

    from app.modules.search.repositories.court_decision import (
        CourtDecisionRepository,
    )

    await _seed([_make_decision(case_number="A-1", text_hash="z" * 64)])

    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        repo = CourtDecisionRepository(session)
        collected: list[CourtDecision] = []
        async for batch in repo.iter_unindexed(batch_size=10):
            collected.extend(batch)

    # Session is now closed — accessing related collections must not
    # trigger lazy-load (which would fail on a detached instance).
    assert len(collected) == 1
    decision = collected[0]
    assert len(decision.participants) == 1
    assert decision.participants[0].name == "ООО Ромашка"
    assert len(decision.norms) == 1
    assert decision.norms[0].article == "506"


@pytest.mark.asyncio
async def test_iter_all_includes_indexed_rows(clean_search_tables):
    from app.modules.search.repositories.court_decision import (
        CourtDecisionRepository,
    )

    ids = await _seed(
        [
            _make_decision(case_number="A-1", text_hash="a" * 64, es_indexed=True),
            _make_decision(case_number="A-2", text_hash="b" * 64, es_indexed=False),
        ]
    )

    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        repo = CourtDecisionRepository(session)
        seen: list[int] = []
        async for batch in repo.iter_all(batch_size=100):
            seen.extend(d.id for d in batch)

    assert seen == ids  # both rows in id order, regardless of flag


@pytest.mark.asyncio
async def test_mark_indexed_flips_flag_in_bulk(clean_search_tables):
    from app.modules.search.repositories.court_decision import (
        CourtDecisionRepository,
    )

    ids = await _seed(
        [
            _make_decision(case_number="A-1", text_hash="1" * 64),
            _make_decision(case_number="A-2", text_hash="2" * 64),
            _make_decision(case_number="A-3", text_hash="3" * 64),
        ]
    )

    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        repo = CourtDecisionRepository(session)
        await repo.mark_indexed([ids[0], ids[1]])
        await session.commit()

    async with sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(CourtDecision).order_by(CourtDecision.id)
                )
            )
            .scalars()
            .all()
        )

    flags = {row.id: row.es_indexed for row in rows}
    assert flags[ids[0]] is True
    assert flags[ids[1]] is True
    assert flags[ids[2]] is False  # untouched


@pytest.mark.asyncio
async def test_mark_indexed_empty_list_is_noop(clean_search_tables):
    """Empty input must short-circuit — running ``UPDATE ... WHERE id IN ()``
    against Postgres is a syntax error, so the repo guards it explicitly."""

    from app.modules.search.repositories.court_decision import (
        CourtDecisionRepository,
    )

    await _seed([_make_decision(case_number="A-1", text_hash="9" * 64)])

    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        repo = CourtDecisionRepository(session)
        # Should simply return without raising.
        await repo.mark_indexed([])
        await session.commit()

    # And the row's flag is unchanged.
    async with sessionmaker() as session:
        row = (await session.execute(select(CourtDecision))).scalar_one()
        assert row.es_indexed is False


# ---------------------------------------------------------------------------
# Reindex script tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reindex_default_indexes_unindexed_and_flips_flag(
    clean_search_tables, clean_es_index, reindex_test_index
):
    es = clean_es_index

    ids = await _seed(
        [
            _make_decision(case_number="A-1", text_hash="d1" + "0" * 62),
            _make_decision(case_number="A-2", text_hash="d2" + "0" * 62),
        ]
    )

    exit_code = await reindex_es._run(_ns(batch_size=10))
    assert exit_code == 0

    # Refresh so the bulk-indexed docs are visible to the search API.
    await es.indices.refresh(index=TEST_ES_INDEX)

    for decision_id in ids:
        doc = await es.get(index=TEST_ES_INDEX, id=str(decision_id))
        assert doc["_source"]["id"] == decision_id

    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        rows = (
            (await session.execute(select(CourtDecision))).scalars().all()
        )
    assert all(row.es_indexed is True for row in rows)


@pytest.mark.asyncio
async def test_reindex_all_reindexes_everything_without_touching_flag(
    clean_search_tables, clean_es_index, reindex_test_index
):
    """``--all`` rebuilds the index but does NOT call mark_indexed —
    the flag in PG is meaningful only for the unindexed-backfill path,
    so a full rebuild must leave it alone (matches the comment in the
    script about flag state being irrelevant to ``--all``)."""

    es = clean_es_index

    ids = await _seed(
        [
            _make_decision(case_number="A-1", text_hash="e1" + "0" * 62, es_indexed=True),
        ]
    )

    exit_code = await reindex_es._run(_ns(all=True, batch_size=10))
    assert exit_code == 0

    await es.indices.refresh(index=TEST_ES_INDEX)
    doc = await es.get(index=TEST_ES_INDEX, id=str(ids[0]))
    assert doc["_source"]["case_number"] == "A-1"

    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        row = (await session.execute(select(CourtDecision))).scalar_one()
        # Flag was True before — should still be True (not touched, not
        # cleared). The point: --all doesn't run UPDATE.
        assert row.es_indexed is True


@pytest.mark.asyncio
async def test_reindex_dry_run_writes_nothing(
    clean_search_tables, clean_es_index, reindex_test_index
):
    es = clean_es_index

    await _seed(
        [_make_decision(case_number="A-1", text_hash="f1" + "0" * 62)]
    )

    exit_code = await reindex_es._run(_ns(dry_run=True, batch_size=10))
    assert exit_code == 0

    # ES index exists (created by clean_es_index) but stays empty.
    await es.indices.refresh(index=TEST_ES_INDEX)
    count = await es.count(index=TEST_ES_INDEX)
    assert count["count"] == 0

    # PG flag untouched.
    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        row = (await session.execute(select(CourtDecision))).scalar_one()
        assert row.es_indexed is False
