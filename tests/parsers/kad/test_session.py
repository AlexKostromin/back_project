from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.parsers.kad.session import (
    KadSessionProvider,
    NullKadSessionProvider,
    PlaywrightKadSessionProvider,
    SessionCookies,
)


class TestSessionCookies:
    """Unit tests for SessionCookies frozen DTO."""

    def test_is_expired_returns_false_for_fresh_cookies(self):
        """Fresh cookies with future expiration should not be expired."""
        now = datetime.now(timezone.utc)
        cookies = SessionCookies(
            cookies={"__ddg8_": "value1", "__ddg10_": "value2"},
            obtained_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert not cookies.is_expired()

    def test_is_expired_returns_true_for_expired_cookies(self):
        """Cookies with past expiration time should be expired."""
        now = datetime.now(timezone.utc)
        cookies = SessionCookies(
            cookies={"__ddg8_": "value1"},
            obtained_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
        assert cookies.is_expired()

    def test_is_expired_uses_provided_now(self):
        """is_expired should respect the provided 'now' parameter for deterministic tests."""
        fixed_now = datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)
        cookies = SessionCookies(
            cookies={"__ddg8_": "value1"},
            obtained_at=fixed_now - timedelta(hours=1),
            expires_at=fixed_now + timedelta(minutes=30),
        )

        # Before expiration
        assert not cookies.is_expired(now=fixed_now)

        # At expiration
        assert cookies.is_expired(now=fixed_now + timedelta(minutes=30))

        # After expiration
        assert cookies.is_expired(now=fixed_now + timedelta(hours=1))

    def test_session_cookies_frozen(self):
        """SessionCookies should be immutable (frozen Pydantic model)."""
        cookies = SessionCookies(
            cookies={"__ddg8_": "value1"},
            obtained_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        with pytest.raises(ValidationError, match="Instance is frozen"):
            cookies.cookies = {}  # type: ignore[misc]

    def test_repr_does_not_leak_cookie_values(self):
        cookies = SessionCookies(
            cookies={"__ddg8_": "very_secret_token", "__ddg9_": "1.2.3.4"},
            obtained_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        rendered = repr(cookies)
        assert "very_secret_token" not in rendered
        assert "1.2.3.4" not in rendered
        assert "<2 masked>" in rendered
        assert str(cookies) == rendered


class TestPlaywrightProviderBaseUrlValidation:
    """SSRF protection on base_url — must reject anything outside arbitr.ru / non-https."""

    @pytest.mark.parametrize(
        "bad_url",
        [
            "http://kad.arbitr.ru",
            "https://attacker.com",
            "https://evil.arbitr.ru.attacker.com",
            "https://169.254.169.254/latest/meta-data/",
            "https://localhost:8080",
            "javascript:alert(1)",
            "file:///etc/passwd",
        ],
    )
    def test_rejects_disallowed_base_url(self, bad_url):
        with pytest.raises(ValueError):
            PlaywrightKadSessionProvider(base_url=bad_url)

    @pytest.mark.parametrize(
        "good_url",
        [
            "https://kad.arbitr.ru",
            "https://kad.arbitr.ru/",
            "https://mkad.arbitr.ru",
            "https://arbitr.ru",
        ],
    )
    def test_accepts_allowed_base_url(self, good_url):
        provider = PlaywrightKadSessionProvider(base_url=good_url)
        assert provider is not None


class TestNullKadSessionProvider:
    """Unit tests for NullKadSessionProvider."""

    @pytest.mark.asyncio
    async def test_null_session_provider_raises(self):
        """NullKadSessionProvider should always raise RuntimeError."""
        provider = NullKadSessionProvider()
        with pytest.raises(
            RuntimeError,
            match="NullKadSessionProvider has no session — wire PlaywrightKadSessionProvider",
        ):
            await provider.get_cookies()


class _FakePlaywrightProvider(PlaywrightKadSessionProvider):
    """
    Test double for PlaywrightKadSessionProvider.

    Overrides _fetch_fresh to return fixed cookies without launching Playwright.
    Tracks call count to verify caching behavior.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fetch_count = 0
        self._fixed_cookies = SessionCookies(
            cookies={"__ddg8_": "test_value", "__ddg10_": "test_value2"},
            obtained_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=23),
        )

    async def _fetch_fresh(self) -> SessionCookies:
        """Return pre-built cookies instead of launching Playwright."""
        self.fetch_count += 1
        # Simulate async delay
        await asyncio.sleep(0.01)
        return self._fixed_cookies


class TestPlaywrightKadSessionProviderCaching:
    """Unit tests for caching and concurrency behavior using fake provider."""

    @pytest.mark.asyncio
    async def test_provider_caches_cookies_until_expiration(self):
        """Provider should cache cookies and refresh only when expired."""
        provider = _FakePlaywrightProvider()

        # First call triggers fetch
        cookies1 = await provider.get_cookies()
        assert provider.fetch_count == 1
        assert "__ddg8_" in cookies1.cookies

        # Second call uses cache
        cookies2 = await provider.get_cookies()
        assert provider.fetch_count == 1  # No additional fetch
        assert cookies2 is cookies1  # Same instance

        # Force expiration by manually setting cached cookies to expired state
        expired_cookies = SessionCookies(
            cookies={"__ddg8_": "expired"},
            obtained_at=datetime.now(timezone.utc) - timedelta(hours=24),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        provider._cached = expired_cookies

        # Third call triggers refresh
        cookies3 = await provider.get_cookies()
        assert provider.fetch_count == 2  # Fresh fetch
        assert cookies3 is not expired_cookies

    @pytest.mark.asyncio
    async def test_provider_get_cookies_is_lock_protected(self):
        """Concurrent get_cookies calls should trigger only one _fetch_fresh (lock protection)."""
        provider = _FakePlaywrightProvider()

        # Launch two concurrent get_cookies calls
        results = await asyncio.gather(
            provider.get_cookies(),
            provider.get_cookies(),
        )

        # Both should return the same cookies
        assert results[0] is results[1]

        # _fetch_fresh should be called exactly once (lock worked)
        assert provider.fetch_count == 1
