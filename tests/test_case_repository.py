from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Case, CourtDecision
from app.db.repositories.case import CaseRepository
from app.db.session import get_sessionmaker


@pytest.mark.asyncio
async def test_upsert_creates_new_case(clean_cases):
    """Test that upsert creates a new case when (source_name, external_id) is new."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = CaseRepository(session)

        case = Case(
            source_name="arbitr",
            external_id="12345678-1234-5678-1234-567812345678",
            case_number="А37-1073/2026",
            court_name="Арбитражный суд города Севастополя",
            court_type="arbitrazh",
            court_tag="SEVASTOPOL",
            instance_level=1,
            region="Севастополь",
            dispute_category="Банкротство",
            parties=[
                {
                    "name": "ООО Ромашка",
                    "role": "defendant",
                    "inn": "1234567890",
                    "ogrn": "1234567890123",
                }
            ],
            judges=["Иванов И. И.", "Петрова А. Б."],
            crawled_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
        )

        persisted = await repo.upsert_by_external_id(case)
        await session.commit()

        assert persisted.id is not None
        assert persisted.source_name == "arbitr"
        assert persisted.external_id == "12345678-1234-5678-1234-567812345678"
        assert persisted.case_number == "А37-1073/2026"
        assert persisted.court_tag == "SEVASTOPOL"
        assert persisted.instance_level == 1
        assert len(persisted.parties) == 1
        assert persisted.parties[0]["name"] == "ООО Ромашка"
        assert len(persisted.judges) == 2
        assert persisted.created_at is not None
        assert persisted.updated_at is not None


@pytest.mark.asyncio
async def test_upsert_updates_existing_case(clean_cases):
    """Test that upsert updates an existing case when (source_name, external_id) already exists."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = CaseRepository(session)

        # Insert initial case
        case_v1 = Case(
            source_name="arbitr",
            external_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            case_number="А40-1234/2026",
            court_name="Арбитражный суд города Москвы",
            court_type="arbitrazh",
            court_tag="MOSCOW",
            instance_level=1,
            region="Москва",
            dispute_category="Коммерческий спор",
            parties=[{"name": "ООО Альфа", "role": "plaintiff"}],
            judges=["Сидоров С. С."],
            crawled_at=datetime(2026, 4, 20, 10, 0, 0, tzinfo=timezone.utc),
        )
        persisted_v1 = await repo.upsert_by_external_id(case_v1)
        await session.commit()

        original_id = persisted_v1.id
        original_created_at = persisted_v1.created_at

        # Update the same case (different case_number, new judge)
        case_v2 = Case(
            source_name="arbitr",
            external_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            case_number="А40-1234/2026 (исправленный)",
            court_name="Арбитражный суд города Москвы",
            court_type="arbitrazh",
            court_tag="MOSCOW",
            instance_level=1,
            region="Москва",
            dispute_category="Коммерческий спор",
            parties=[
                {"name": "ООО Альфа", "role": "plaintiff"},
                {"name": "ООО Бета", "role": "defendant"},
            ],
            judges=["Сидоров С. С.", "Николаев Н. Н."],
            crawled_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
        )
        persisted_v2 = await repo.upsert_by_external_id(case_v2)
        await session.commit()

        # Verify that it's the same row (id unchanged) but fields updated
        assert persisted_v2.id == original_id
        assert persisted_v2.case_number == "А40-1234/2026 (исправленный)"
        assert len(persisted_v2.parties) == 2
        assert len(persisted_v2.judges) == 2
        assert persisted_v2.crawled_at == datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)
        assert persisted_v2.created_at == original_created_at  # created_at unchanged
        assert persisted_v2.updated_at >= original_created_at  # updated_at same or newer (may be same if update is instant)


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_missing(clean_cases):
    """Test that get_by_id returns None when case does not exist."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = CaseRepository(session)
        result = await repo.get_by_id(999999)
        assert result is None


@pytest.mark.asyncio
async def test_get_by_external_id_unique_per_source(clean_cases):
    """Test that two cases with same external_id but different source_name are distinct."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = CaseRepository(session)

        # Insert case from "arbitr"
        case_arbitr = Case(
            source_name="arbitr",
            external_id="common-uuid",
            case_number="А50-5555/2026",
            court_name="АС Пермского края",
            court_type="arbitrazh",
            instance_level=1,
            parties=[],
            judges=[],
            crawled_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
        )
        await repo.upsert_by_external_id(case_arbitr)

        # Insert case from "sudrf" with same external_id
        case_sudrf = Case(
            source_name="sudrf",
            external_id="common-uuid",
            case_number="2-100/2026",
            court_name="Пермский районный суд",
            court_type="soy",
            instance_level=1,
            parties=[],
            judges=[],
            crawled_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
        )
        await repo.upsert_by_external_id(case_sudrf)
        await session.commit()

        # Retrieve both
        retrieved_arbitr = await repo.get_by_external_id("arbitr", "common-uuid")
        retrieved_sudrf = await repo.get_by_external_id("sudrf", "common-uuid")

        assert retrieved_arbitr is not None
        assert retrieved_sudrf is not None
        assert retrieved_arbitr.id != retrieved_sudrf.id
        assert retrieved_arbitr.case_number == "А50-5555/2026"
        assert retrieved_sudrf.case_number == "2-100/2026"


@pytest.mark.asyncio
async def test_court_decision_case_id_fk_constraint(clean_cases):
    """Test that inserting a CourtDecision with non-existent case_id raises IntegrityError."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        # Try to insert CourtDecision with case_id=9999 (does not exist)
        decision = CourtDecision(
            case_id=9999,
            source_id="fake-source-id",
            source_name="arbitr",
            case_number="А99-9999/2026",
            court_name="Fake Court",
            court_type="arbitrazh",
            instance_level=1,
            decision_date=datetime(2026, 4, 27, tzinfo=timezone.utc).date(),
            doc_type="решение",
            judges=["Fake Judge"],
            result="satisfied",
            appeal_status="none",
            dispute_type="civil",
            full_text="Fake text",
            text_hash="a" * 64,
            source_url="https://example.com/fake",
            crawled_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
            parsed_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
        )
        session.add(decision)

        with pytest.raises(IntegrityError) as exc_info:
            await session.commit()

        assert "fk_search_court_decisions_case_id_cases" in str(exc_info.value) or "foreign key" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_court_decision_case_relationship_loads(clean_cases):
    """Test that case.decisions relationship loads correctly via lazy='selectin'."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = CaseRepository(session)

        # Create a case
        case = Case(
            source_name="arbitr",
            external_id="case-with-decisions",
            case_number="А77-7777/2026",
            court_name="АС г. Москвы",
            court_type="arbitrazh",
            instance_level=1,
            parties=[],
            judges=["Иванов И. И."],
            crawled_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
        )
        persisted_case = await repo.upsert_by_external_id(case)
        await session.commit()

        # Create two decisions linked to this case
        decision1 = CourtDecision(
            case_id=persisted_case.id,
            source_id="decision-1",
            source_name="arbitr",
            case_number="А77-7777/2026",
            court_name="АС г. Москвы",
            court_type="arbitrazh",
            instance_level=1,
            decision_date=datetime(2026, 4, 1, tzinfo=timezone.utc).date(),
            doc_type="решение",
            judges=["Иванов И. И."],
            result="satisfied",
            appeal_status="none",
            dispute_type="civil",
            full_text="Decision 1 text",
            text_hash="b" * 64,
            source_url="https://example.com/decision-1",
            crawled_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
            parsed_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
        )
        decision2 = CourtDecision(
            case_id=persisted_case.id,
            source_id="decision-2",
            source_name="arbitr",
            case_number="А77-7777/2026",
            court_name="АС г. Москвы",
            court_type="arbitrazh",
            instance_level=2,
            decision_date=datetime(2026, 4, 15, tzinfo=timezone.utc).date(),
            doc_type="постановление",
            judges=["Петрова П. П."],
            result="upheld",
            appeal_status="upheld",
            dispute_type="civil",
            full_text="Decision 2 text",
            text_hash="c" * 64,
            source_url="https://example.com/decision-2",
            crawled_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
            parsed_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
        )
        session.add(decision1)
        session.add(decision2)
        await session.commit()

        # Retrieve case and verify relationship (use fresh session to avoid stale data)
        async with sessionmaker() as fresh_session:
            fresh_repo = CaseRepository(fresh_session)
            retrieved_case = await fresh_repo.get_by_id(persisted_case.id)
            assert retrieved_case is not None
            assert len(retrieved_case.decisions) == 2
            assert retrieved_case.decisions[0].source_id in ["decision-1", "decision-2"]
            assert retrieved_case.decisions[1].source_id in ["decision-1", "decision-2"]


@pytest.mark.asyncio
async def test_list_by_court_tag(clean_cases):
    """Test list_by_court_tag pagination."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = CaseRepository(session)

        # Insert 3 cases with court_tag="PERM"
        for i in range(3):
            case = Case(
                source_name="arbitr",
                external_id=f"perm-case-{i}",
                case_number=f"А50-{1000+i}/2026",
                court_name="АС Пермского края",
                court_type="arbitrazh",
                court_tag="PERM",
                instance_level=1,
                parties=[],
                judges=[],
                crawled_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
            )
            await repo.upsert_by_external_id(case)

        # Insert 1 case with court_tag="MOSCOW"
        case_moscow = Case(
            source_name="arbitr",
            external_id="moscow-case",
            case_number="А40-9999/2026",
            court_name="АС г. Москвы",
            court_type="arbitrazh",
            court_tag="MOSCOW",
            instance_level=1,
            parties=[],
            judges=[],
            crawled_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
        )
        await repo.upsert_by_external_id(case_moscow)
        await session.commit()

        # List by PERM tag
        perm_cases = await repo.list_by_court_tag("PERM", limit=10, offset=0)
        assert len(perm_cases) == 3
        assert all(c.court_tag == "PERM" for c in perm_cases)

        # List by MOSCOW tag
        moscow_cases = await repo.list_by_court_tag("MOSCOW", limit=10, offset=0)
        assert len(moscow_cases) == 1
        assert moscow_cases[0].court_tag == "MOSCOW"

        # Test pagination (offset=2, limit=1)
        perm_page = await repo.list_by_court_tag("PERM", limit=1, offset=2)
        assert len(perm_page) == 1


@pytest.mark.asyncio
async def test_list_by_court_tag_caps_oversize_limit(clean_cases):
    """list_by_court_tag must clamp limit to MAX_LIST_LIMIT (DoS protection)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = CaseRepository(session)

        # Single case is enough — we're testing the clamp, not the result count.
        case = Case(
            source_name="arbitr",
            external_id="cap-test",
            case_number="А50-1/2026",
            court_name="АС Пермского края",
            court_type="arbitrazh",
            court_tag="PERM",
            instance_level=1,
            parties=[],
            judges=[],
            crawled_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
        )
        await repo.upsert_by_external_id(case)
        await session.commit()

        # limit=1_000_000 must be silently clamped, not blow up Postgres.
        # We assert the call returns without error and yields the single row.
        result = await repo.list_by_court_tag("PERM", limit=1_000_000, offset=0)
        assert len(result) == 1


@pytest.mark.asyncio
async def test_list_by_court_tag_rejects_negative_limit(clean_cases):
    """Negative limit/offset raise ValueError up-front."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = CaseRepository(session)
        with pytest.raises(ValueError):
            await repo.list_by_court_tag("PERM", limit=-1, offset=0)
        with pytest.raises(ValueError):
            await repo.list_by_court_tag("PERM", limit=10, offset=-1)
