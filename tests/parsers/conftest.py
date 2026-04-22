from __future__ import annotations

import json
from datetime import date
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
        "judges": ["Иванов И.И."],
        "decision_date": "2025-03-15",
        "category": "Взыскание задолженности",
        "result": "Удовлетворено",
        "appeal_status": None,
        "participants": ["ООО Ромашка", "АО Василёк"],
        "full_text": "Решение суда по делу А40-12345/2025...",
    }

    # Another valid decision
    valid_case_002 = {
        "case_number": "А41-67890/2024",
        "court_name": "Арбитражный суд Московской области",
        "judges": ["Петрова М.С.", "Сидоров А.К."],
        "decision_date": "2024-12-20",
        "category": "Налоговые споры",
        "result": "Отказано",
        "appeal_status": "Обжаловано",
        "participants": ["ИП Смирнов", "ИФНС №5"],
        "full_text": "Решение суда по делу А41-67890/2024...",
    }

    # Invalid: missing required field (case_number)
    invalid_missing_field = {
        "court_name": "Арбитражный суд",
        "judges": [],
        "decision_date": "2025-01-01",
        "participants": [],
        "full_text": "Текст",
    }

    # Invalid: wrong type for decision_date
    invalid_wrong_type = {
        "case_number": "А00-00000/2000",
        "court_name": "Суд",
        "judges": ["Судья"],
        "decision_date": "not-a-date",
        "category": None,
        "result": None,
        "appeal_status": None,
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
    (fixtures_dir / "invalid_wrong_type.json").write_text(
        json.dumps(invalid_wrong_type, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Invalid JSON syntax
    (fixtures_dir / "invalid_json.json").write_text("{not valid json", encoding="utf-8")

    return fixtures_dir
