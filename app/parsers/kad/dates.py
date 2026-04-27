from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

# Russia abolished DST in 2014; MSK is fixed UTC+3 from then onward.
MSK_OFFSET = timezone(timedelta(hours=3))

ASPNET_DATE_PATTERN = re.compile(r"^/Date\((-?\d+)\)/$")


def parse_aspnet_date(s: str) -> datetime:
    """Parse ASP.NET date format /Date(ms)/ to UTC datetime.

    Args:
        s: Date string in format /Date(1234567890000)/

    Returns:
        datetime in UTC timezone

    Raises:
        ValueError: If string is not in expected format

    Examples:
        >>> parse_aspnet_date("/Date(1609459200000)/")
        datetime.datetime(2021, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)
    """
    match = ASPNET_DATE_PATTERN.match(s)
    if not match:
        raise ValueError(
            f"Invalid ASP.NET date format: expected /Date(ms)/, got: {s!r}"
        )

    milliseconds = int(match.group(1))
    seconds = milliseconds / 1000

    # Windows doesn't support negative timestamps in fromtimestamp
    # Use datetime.fromtimestamp for positive, timedelta for negative
    if seconds >= 0:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    else:
        # Epoch (1970-01-01 00:00:00 UTC) + negative offset
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        return epoch + timedelta(seconds=seconds)


def aspnet_date_to_msk_date(s: str) -> date:
    """Parse ASP.NET date format /Date(ms)/ to Moscow date.

    Converts UTC timestamp to Moscow timezone and returns date component.
    Legal documents are dated according to Moscow time regardless of court location.

    Args:
        s: Date string in format /Date(1234567890000)/

    Returns:
        date in Moscow time (UTC+3)

    Raises:
        ValueError: If string is not in expected format

    Examples:
        >>> aspnet_date_to_msk_date("/Date(1609459200000)/")
        datetime.date(2021, 1, 1)
    """
    utc_dt = parse_aspnet_date(s)
    msk_dt = utc_dt.astimezone(MSK_OFFSET)
    return msk_dt.date()
