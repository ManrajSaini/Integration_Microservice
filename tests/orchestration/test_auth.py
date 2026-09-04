from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, Install
from app.errors import TokenRefreshError
from app.models.schemas import TokenSet
from app.orchestration.auth import ensure_fresh_access_token


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as s:
        yield s

    await engine.dispose()


async def _make_install(session, expires_in_seconds: float) -> Install:
    install = Install(
        hub_id="12345",
        access_token="stale-token",
        refresh_token="refresh-1",
        access_token_expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
        scopes="oauth",
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(install)
    await session.commit()
    await session.refresh(install)
    return install


class FakeAdapter:
    """Fakes the ProviderAdapter Protocol's refresh_access_token — per
    constitution.md §7, never mock httpx at this layer."""

    provider_name = "fake"

    def __init__(self, refresh_result=None, refresh_error=None):
        self.refresh_result = refresh_result
        self.refresh_error = refresh_error
        self.refresh_calls: list[str] = []

    async def refresh_access_token(self, refresh_token: str) -> TokenSet:
        self.refresh_calls.append(refresh_token)
        if self.refresh_error:
            raise self.refresh_error
        return self.refresh_result


async def test_ensure_fresh_access_token_skips_refresh_when_not_near_expiry(session):
    install = await _make_install(session, expires_in_seconds=1500)  # well over 20% of 1800s
    adapter = FakeAdapter()

    result = await ensure_fresh_access_token(session, adapter, install)

    assert result.access_token == "stale-token"
    assert adapter.refresh_calls == []


async def test_ensure_fresh_access_token_refreshes_when_near_expiry(session):
    install = await _make_install(session, expires_in_seconds=60)  # under 20% of 1800s (=360s)
    adapter = FakeAdapter(
        refresh_result=TokenSet(
            access_token="fresh-token",
            refresh_token="refresh-1",
            expires_in=1800,
            scopes=["oauth"],
            account_id="12345",
        )
    )

    result = await ensure_fresh_access_token(session, adapter, install)

    assert result.access_token == "fresh-token"
    assert adapter.refresh_calls == ["refresh-1"]


async def test_ensure_fresh_access_token_marks_needs_reauth_on_invalid_grant(session):
    install = await _make_install(session, expires_in_seconds=60)
    adapter = FakeAdapter(
        refresh_error=TokenRefreshError("refresh token is invalid, expired or revoked")
    )

    with pytest.raises(TokenRefreshError):
        await ensure_fresh_access_token(session, adapter, install)

    assert install.status == "needs_reauth"
