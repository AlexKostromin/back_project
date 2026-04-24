from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict


class SessionCookies(BaseModel):
    """
    Immutable container for DDoS-Guard session cookies from kad.arbitr.ru.

    Why frozen: cookies are treated as values, not mutable state. If cookies
    expire, we create a new SessionCookies instance rather than mutating.
    """

    model_config = ConfigDict(frozen=True)

    cookies: dict[str, str]
    obtained_at: datetime
    expires_at: datetime

    def __repr__(self) -> str:
        # SECURITY: never expose cookie values in logs/tracebacks. Caller must
        # access .cookies explicitly when handing off to httpx.
        return (
            f"SessionCookies(cookies=<{len(self.cookies)} masked>, "
            f"obtained_at={self.obtained_at.isoformat()}, "
            f"expires_at={self.expires_at.isoformat()})"
        )

    __str__ = __repr__

    def is_expired(self, *, now: datetime | None = None) -> bool:
        """
        Check if cookies are expired.

        Args:
            now: Override current time for testing. If None, uses timezone-aware UTC now.

        Returns:
            True if cookies are past their expiration time.
        """
        effective_now = now if now is not None else datetime.now(timezone.utc)
        return effective_now >= self.expires_at


class KadSessionProvider(ABC):
    """
    Abstract provider for kad.arbitr.ru session cookies.

    Why abstract: allows tests to inject NullKadSessionProvider and isolates
    Playwright logic from business code.
    """

    @abstractmethod
    async def get_cookies(self) -> SessionCookies:
        """
        Return valid session cookies, refreshing if expired.

        Raises:
            RuntimeError: If provider cannot obtain cookies (e.g., Playwright failure).
        """
        ...


class NullKadSessionProvider(KadSessionProvider):
    """
    Null-object provider that always fails.

    Why: explicit marker that no session is configured; fails fast in tests or
    environments where Playwright is not wired. Better than silently returning
    empty cookies.
    """

    async def get_cookies(self) -> SessionCookies:
        raise RuntimeError(
            "NullKadSessionProvider has no session — wire PlaywrightKadSessionProvider in production"
        )


class PlaywrightKadSessionProvider(KadSessionProvider):
    """
    Obtains DDoS-Guard session cookies via headless Chromium + playwright-stealth.

    Why hybrid approach: kad.arbitr.ru serves JS challenge on first request. We use
    Playwright to solve it once, extract cookies, then reuse them with httpx for
    24h. This avoids expensive browser overhead on every HTTP request.

    Threading model:
    - _lock ensures only one Playwright instance runs concurrently, even if
      multiple get_cookies() calls arrive simultaneously (e.g., from parallel tasks).
    - Cache avoids repeated browser launches until cookies expire.
    """

    _ALLOWED_HOST_SUFFIX = ".arbitr.ru"

    def __init__(
        self,
        *,
        base_url: str = "https://kad.arbitr.ru",
        ttl_seconds: int = 23 * 3600,
        headless: bool = True,
        user_agent: str | None = None,
    ):
        """
        Initialize Playwright session provider.

        Args:
            base_url: Target URL for challenge completion (kad.arbitr.ru homepage).
            ttl_seconds: Cookie lifetime in seconds. Default 23h leaves 1h safety
                margin before DDoS-Guard's typical 24h cookie expiration.
            headless: Run Chromium in headless mode. Set False for local debugging.
            user_agent: Override default Chromium user-agent. If None, uses
                Chromium's standard UA (avoids suspicious custom strings).
        """
        # SSRF protection: only https + arbitr.ru domain are reachable. Tests
        # that need a different target should override _fetch_fresh (which is
        # what the existing fake providers already do — base_url is never read).
        parsed = urlparse(base_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https":
            raise ValueError(f"base_url must use https scheme, got: {parsed.scheme!r}")
        if host != "arbitr.ru" and not host.endswith(self._ALLOWED_HOST_SUFFIX):
            raise ValueError(f"base_url host must be arbitr.ru or *.arbitr.ru, got: {host!r}")

        self._base_url = base_url
        self._ttl_seconds = ttl_seconds
        self._headless = headless
        self._user_agent = user_agent
        self._cached: SessionCookies | None = None
        self._lock = asyncio.Lock()

    async def get_cookies(self) -> SessionCookies:
        """
        Return valid session cookies, triggering Playwright refresh if expired.

        Returns:
            SessionCookies with at least ttl_seconds validity remaining.

        Raises:
            RuntimeError: If Playwright fails to obtain cookies (timeout, network error).
        """
        if self._cached is not None and not self._cached.is_expired():
            return self._cached

        async with self._lock:
            # Double-check after acquiring lock: another task may have refreshed while we waited
            if self._cached is not None and not self._cached.is_expired():
                return self._cached

            self._cached = await self._fetch_fresh()
            return self._cached

    async def _fetch_fresh(self) -> SessionCookies:
        """
        Launch Playwright, solve DDoS-Guard challenge, extract cookies.

        Why separate method: allows tests to override with mock implementation
        without duplicating cache/lock logic.

        Returns:
            Fresh SessionCookies with __ddg8_, __ddg9_, __ddg10_.

        Raises:
            RuntimeError: If cookies not obtained within timeout or missing required keys.
        """
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self._headless)
            context_kwargs = (
                {"user_agent": self._user_agent} if self._user_agent else {}
            )
            context = await browser.new_context(**context_kwargs)

            try:
                ddg_cookies = await self._solve_challenge(context)
                return self._build_session_cookies(ddg_cookies)
            finally:
                await browser.close()

    async def _solve_challenge(self, context) -> dict[str, str]:
        """
        Open page, apply stealth, wait for DDoS-Guard cookies.

        Returns:
            Dict of DDoS-Guard cookies.

        Raises:
            RuntimeError: If cookies not obtained within timeout or missing required keys.
        """
        from playwright_stealth import stealth_async

        page = await context.new_page()
        await stealth_async(page)

        await page.goto(self._base_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_function(
            "document.cookie.includes('__ddg8_') && document.cookie.includes('__ddg10_')",
            timeout=30000,
        )

        all_cookies = await context.cookies()
        ddg_cookies = {
            c["name"]: c["value"]
            for c in all_cookies
            if c["name"].startswith("__ddg")
        }

        if "__ddg8_" not in ddg_cookies or "__ddg10_" not in ddg_cookies:
            raise RuntimeError(
                f"DDoS-Guard challenge completed but required cookies missing. "
                f"Got: {list(ddg_cookies.keys())}"
            )

        return ddg_cookies

    def _build_session_cookies(self, ddg_cookies: dict[str, str]) -> SessionCookies:
        """Build SessionCookies with TTL from extracted cookies."""
        obtained_at = datetime.now(timezone.utc)
        expires_at = obtained_at + timedelta(seconds=self._ttl_seconds)
        return SessionCookies(
            cookies=ddg_cookies,
            obtained_at=obtained_at,
            expires_at=expires_at,
        )
