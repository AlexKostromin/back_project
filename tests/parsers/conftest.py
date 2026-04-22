from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_fixtures_dir(tmp_path: Path) -> Path:
    """Create temporary directory with JSON fixtures."""
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()

    # Valid decision with all required fields
    valid_case_001 = {
        "case_number": "А40-12345/2025",
        "court_name": "Арбитражный суд города Москвы",
        "court_type": "arbitrazh",
        "instance_level": 1,
        "region": "г. Москва",
        "decision_date": "2025-03-15",
        "publication_date": "2025-03-20",
        "doc_type": "решение",
        "judges": ["Иванов И.И."],
        "result": "satisfied",
        "appeal_status": "none",
        "category": "Взыскание задолженности",
        "dispute_type": "civil",
        "claim_amount": "15000000.00",
        "participants": [
            {"name": "ООО Ромашка", "role": "plaintiff", "inn": "7700000001", "ogrn": None},
            {"name": "АО Василёк", "role": "defendant", "inn": "7700000002", "ogrn": None},
        ],
        "norms": [
            {
                "law_name": "ГК РФ",
                "article": "10",
                "part": "1",
                "paragraph": None,
                "raw_ref": "ст. 10 ч. 1 ГК РФ",
            }
        ],
        "full_text": "Решение суда по делу А40-12345/2025...",
        "sections": {
            "resolutive": "Удовлетворить исковые требования...",
            "motivational": "Суд установил...",
        },
    }

    # Another valid decision
    valid_case_002 = {
        "case_number": "А41-67890/2024",
        "court_name": "Арбитражный суд Московской области",
        "court_type": "arbitrazh",
        "instance_level": 2,
        "region": "Московская область",
        "decision_date": "2024-12-20",
        "publication_date": None,
        "doc_type": "постановление",
        "judges": ["Петрова М.С.", "Сидоров А.К."],
        "result": "denied",
        "appeal_status": "appealed",
        "category": "Налоговые споры",
        "dispute_type": "admin",
        "claim_amount": None,
        "participants": [
            {"name": "ИП Смирнов", "role": "plaintiff", "inn": None, "ogrn": None},
            {"name": "ИФНС №5", "role": "defendant", "inn": None, "ogrn": None},
        ],
        "norms": [],
        "full_text": "Решение суда по делу А41-67890/2024...",
        "sections": {},
    }

    # Invalid: missing required field (court_type)
    invalid_missing_field = {
        "case_number": "А50-00000/2025",
        "court_name": "Арбитражный суд",
        "instance_level": 1,
        "decision_date": "2025-01-01",
        "doc_type": "решение",
        "judges": [],
        "result": "satisfied",
        "dispute_type": "civil",
        "participants": [],
        "full_text": "Текст",
    }

    # Invalid: wrong enum value for court_type
    invalid_enum_value = {
        "case_number": "А60-00000/2025",
        "court_name": "Суд",
        "court_type": "invalid_type",
        "instance_level": 1,
        "decision_date": "2025-01-01",
        "doc_type": "решение",
        "judges": ["Судья"],
        "result": "satisfied",
        "dispute_type": "civil",
        "participants": [],
        "full_text": "Текст",
    }

    # Invalid: wrong type for decision_date
    invalid_wrong_type = {
        "case_number": "А00-00000/2000",
        "court_name": "Суд",
        "court_type": "arbitrazh",
        "instance_level": 1,
        "decision_date": "not-a-date",
        "doc_type": "решение",
        "judges": ["Судья"],
        "result": "satisfied",
        "dispute_type": "civil",
        "participants": [],
        "full_text": "Текст",
    }

    # Write fixtures
    (fixtures_dir / "case_001.json").write_text(
        json.dumps(valid_case_001, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (fixtures_dir / "case_002.json").write_text(
        json.dumps(valid_case_002, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (fixtures_dir / "invalid_missing_field.json").write_text(
        json.dumps(invalid_missing_field, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (fixtures_dir / "invalid_enum_value.json").write_text(
        json.dumps(invalid_enum_value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (fixtures_dir / "invalid_wrong_type.json").write_text(
        json.dumps(invalid_wrong_type, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Invalid JSON syntax
    (fixtures_dir / "invalid_json.json").write_text("{not valid json", encoding="utf-8")

    return fixtures_dir
