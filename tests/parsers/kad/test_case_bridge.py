from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.db.models.case import Case
from app.db.repositories.case import CaseRepository
from app.db.session import get_sessionmaker
from app.parsers.kad.case_bridge import KAD_SOURCE_NAME, _to_case_orm, save_case_summary
from app.parsers.kad.parser import KadArbitrParser
from app.parsers.kad.schemas import KadCaseSummary, KadParty
from app.parsers.schemas import CourtType, ParticipantRole


@pytest.fixture
def fixture_html() -> str:
    """Load test fixture HTML."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "card_30f36558.html"
    return fixture_path.read_text(encoding="utf-8")


@pytest.fixture
def parsed_summary(fixture_html: str) -> KadCaseSummary:
    """Parse fixture HTML to KadCaseSummary."""
    parser = KadArbitrParser()
    return parser.parse_card(
        fixture_html,
        case_id="30f36558-ebdf-42d4-b576-436abc20b478",
        source_url="https://kad.arbitr.ru/Card/30f36558-ebdf-42d4-b576-436abc20b478",
    )


def test_to_case_orm_maps_required_fields(parsed_summary: KadCaseSummary) -> None:
    """_to_case_orm should map all required fields from KadCaseSummary to Case."""
    case = _to_case_orm(parsed_summary, court_tag="MAGADAN")

    assert case.source_name == KAD_SOURCE_NAME
    assert case.external_id == parsed_summary.case_id
    assert case.case_number == parsed_summary.case_number
    assert case.court_name == parsed_summary.court_name
    assert case.court_type == CourtType.ARBITRAZH.value
    assert case.court_tag == "MAGADAN"
    assert case.instance_level == parsed_summary.instance_level
    assert case.region == parsed_summary.region
    assert case.dispute_category == parsed_summary.dispute_category
    assert case.crawled_at == parsed_summary.crawled_at
    assert isinstance(case.parties, list)
    assert isinstance(case.judges, list)


def test_to_case_orm_serializes_parties_without_none() -> None:
    """_to_case_orm should serialize parties excluding None fields (exclude_none=True)."""
    summary = KadCaseSummary(
        case_id="test-case-123",
        case_number="А00-0000/2026",
        court_name="Тестовый АС",
        court_type=CourtType.ARBITRAZH,
        instance_level=1,
        parties=[
            KadParty(
                name="ООО Тест",
                role=ParticipantRole.PLAINTIFF,
                inn=None,
                ogrn=None,
                address=None,
            )
        ],
        judges=[],
        document_refs=[],
        source_url="https://example.com",
        crawled_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
    )

    case = _to_case_orm(summary, court_tag=None)

    assert len(case.parties) == 1
    party_dict = case.parties[0]
    assert party_dict["name"] == "ООО Тест"
    assert party_dict["role"] == ParticipantRole.PLAINTIFF.value
    assert "inn" not in party_dict
    assert "ogrn" not in party_dict
    assert "address" not in party_dict


def test_to_case_orm_handles_empty_parties_and_judges() -> None:
    """_to_case_orm should handle empty parties and judges lists."""
    summary = KadCaseSummary(
        case_id="empty-case",
        case_number="А00-0000/2026",
        court_name="Тестовый АС",
        court_type=CourtType.ARBITRAZH,
        instance_level=1,
        parties=[],
        judges=[],
        document_refs=[],
        source_url="https://example.com",
        crawled_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
    )

    case = _to_case_orm(summary, court_tag=None)

    assert case.parties == []
    assert case.judges == []


@pytest.mark.asyncio
async def test_save_case_summary_persists_new_case(
    clean_cases, parsed_summary: KadCaseSummary
) -> None:
    """save_case_summary should persist a new case and return it with id."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = CaseRepository(session)

        persisted = await save_case_summary(
            parsed_summary, repo, court_tag="MAGADAN"
        )
        await session.commit()

        assert persisted.id is not None
        assert persisted.source_name == KAD_SOURCE_NAME
        assert persisted.external_id == parsed_summary.case_id
        assert persisted.case_number == parsed_summary.case_number
        assert persisted.court_name == parsed_summary.court_name
        assert persisted.court_type == CourtType.ARBITRAZH.value
        assert persisted.court_tag == "MAGADAN"
        assert persisted.instance_level == parsed_summary.instance_level
        assert persisted.dispute_category == parsed_summary.dispute_category
        assert len(persisted.parties) == len(parsed_summary.parties)
        assert len(persisted.judges) == len(parsed_summary.judges)
        assert persisted.created_at is not None
        assert persisted.updated_at is not None

        # Verify via repository get
        retrieved = await repo.get_by_external_id(
            KAD_SOURCE_NAME, parsed_summary.case_id
        )
        assert retrieved is not None
        assert retrieved.id == persisted.id


@pytest.mark.asyncio
async def test_save_case_summary_is_idempotent(
    clean_cases, parsed_summary: KadCaseSummary
) -> None:
    """save_case_summary should be idempotent (upsert, not duplicate)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = CaseRepository(session)

        # First save
        first = await save_case_summary(parsed_summary, repo, court_tag="MAGADAN")
        await session.commit()

        first_id = first.id
        first_created = first.created_at
        first_updated = first.updated_at

    # Second save in a new session
    async with sessionmaker() as session:
        repo = CaseRepository(session)
        second = await save_case_summary(parsed_summary, repo, court_tag="SEVASTOPOL")
        await session.commit()

        # Should update the same row (id unchanged)
        assert second.id == first_id
        assert second.created_at == first_created
        # updated_at should be same or newer (depending on timing)
        assert second.updated_at >= first_updated
        # court_tag should be updated to new value
        assert second.court_tag == "SEVASTOPOL"

    # Verify only one row exists
    async with sessionmaker() as session:
        repo = CaseRepository(session)
        cases = await repo.list_by_court_tag("SEVASTOPOL", limit=100)
        assert len(cases) == 1
        assert cases[0].id == first_id
