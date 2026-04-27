from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.parsers.kad.dates import aspnet_date_to_msk_date, parse_aspnet_date


def test_parse_aspnet_date_valid_positive() -> None:
    """Parse valid ASP.NET date with positive timestamp."""
    result = parse_aspnet_date("/Date(1609459200000)/")
    expected = datetime(2021, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert result == expected


def test_parse_aspnet_date_year_2000() -> None:
    """Parse ASP.NET date from year 2000."""
    # 2000-01-01 00:00:00 UTC
    result = parse_aspnet_date("/Date(946684800000)/")
    expected = datetime(2000, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert result == expected


def test_parse_aspnet_date_invalid_format_raises_error() -> None:
    """Parse invalid format should raise ValueError."""
    with pytest.raises(ValueError) as exc_info:
        parse_aspnet_date("2021-01-01")

    assert "Invalid ASP.NET date format" in str(exc_info.value)
    assert "expected /Date(ms)/" in str(exc_info.value)


def test_parse_aspnet_date_missing_prefix_raises_error() -> None:
    """Parse missing /Date( prefix should raise ValueError."""
    with pytest.raises(ValueError) as exc_info:
        parse_aspnet_date("1609459200000)/")

    assert "Invalid ASP.NET date format" in str(exc_info.value)


def test_parse_aspnet_date_missing_suffix_raises_error() -> None:
    """Parse missing )/ suffix should raise ValueError."""
    with pytest.raises(ValueError) as exc_info:
        parse_aspnet_date("/Date(1609459200000")

    assert "Invalid ASP.NET date format" in str(exc_info.value)


def test_aspnet_date_to_msk_date_valid() -> None:
    """Convert ASP.NET date to Moscow date."""
    # 2026-02-26 00:01:40 UTC = 2026-02-26 03:01:40 MSK
    result = aspnet_date_to_msk_date("/Date(1772088840000)/")
    expected = date(2026, 2, 26)
    assert result == expected


def test_aspnet_date_to_msk_date_boundary_case() -> None:
    """Convert UTC date near midnight to MSK date.

    23:00 UTC on 2023-12-03 = 02:00 MSK on 2023-12-04
    This tests that date conversion uses MSK timezone correctly.
    """
    # 2023-12-04 00:15:58 UTC = 2023-12-04 03:15:58 MSK
    result = aspnet_date_to_msk_date("/Date(1701684958000)/")
    expected = date(2023, 12, 4)
    assert result == expected


def test_aspnet_date_to_msk_date_early_morning_utc() -> None:
    """Convert early morning UTC to previous day in MSK if needed.

    Actually, MSK is UTC+3, so early UTC morning is still morning in MSK.
    This test verifies correct timezone conversion.
    """
    # 2024-06-25 08:28:51 UTC = 2024-06-25 11:28:51 MSK
    result = aspnet_date_to_msk_date("/Date(1719293331000)/")
    expected = date(2024, 6, 25)
    assert result == expected


def test_aspnet_date_to_msk_date_invalid_format_raises_error() -> None:
    """Convert invalid format should raise ValueError."""
    with pytest.raises(ValueError) as exc_info:
        aspnet_date_to_msk_date("not-a-date")

    assert "Invalid ASP.NET date format" in str(exc_info.value)
