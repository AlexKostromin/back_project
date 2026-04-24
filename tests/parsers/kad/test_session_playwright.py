from __future__ import annotations

import os

import pytest

from app.parsers.kad.session import PlaywrightKadSessionProvider


pytestmark = pytest.mark.skipif(
    os.environ.get("KAD_INTEGRATION_TESTS") != "1",
    reason="set KAD_INTEGRATION_TESTS=1 to run real Playwright tests against kad.arbitr.ru",
)


@pytest.mark.asyncio
async def test_real_playwright_obtains_ddos_guard_cookies():
    """
    Integration test: launch real Playwright against kad.arbitr.ru and solve challenge.

    Why skip-by-default: requires chromium installation (poetry run playwright install chromium)
    and network access to kad.arbitr.ru. Slow (~30s) and flaky in CI without browser binaries.
    Enable locally with KAD_INTEGRATION_TESTS=1.
    """
    provider = PlaywrightKadSessionProvider()
    cookies = await provider.get_cookies()

    assert "__ddg8_" in cookies.cookies
    assert "__ddg10_" in cookies.cookies
    assert not cookies.is_expired()
