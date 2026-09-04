from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.errors import TokenRefreshError
from app.db.models import Base, Install
from app.models.schemas import TokenSet
from app.orchestration import auth as auth_module


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


async def test_ensure_fresh_access_token_skips_refresh_when_not_near_expiry(session, monkeypatch):
    install = await _make_install(session, expires_in_seconds=1500)  # well over 20% of 1800s

    called = {"count": 0}

    async def fake_refresh(refresh_token):
        called["count"] += 1
        raise AssertionError("should not be called")

    monkeypatch.setattr(auth_module.hubspot_oauth, "refresh_access_token", fake_refresh)

    result = await auth_module.ensure_fresh_access_token(session, install)

    assert result.access_token == "stale-token"
    assert called["count"] == 0


async def test_ensure_fresh_access_token_refreshes_when_near_expiry(session, monkeypatch):
    install = await _make_install(session, expires_in_seconds=60)  # under 20% of 1800s (=360s)

    async def fake_refresh(refresh_token):
        assert refresh_token == "refresh-1"
        return TokenSet(
            access_token="fresh-token",
            refresh_token="refresh-1",
            expires_in=1800,
            scopes=["oauth"],
            account_id="12345",
        )

    monkeypatch.setattr(auth_module.hubspot_oauth, "refresh_access_token", fake_refresh)

    result = await auth_module.ensure_fresh_access_token(session, install)

    assert result.access_token == "fresh-token"


async def test_ensure_fresh_access_token_marks_needs_reauth_on_invalid_grant(session, monkeypatch):
    install = await _make_install(session, expires_in_seconds=60)

    async def fake_refresh(refresh_token):
        raise TokenRefreshError("refresh token is invalid, expired or revoked")

    monkeypatch.setattr(auth_module.hubspot_oauth, "refresh_access_token", fake_refresh)

    with pytest.raises(TokenRefreshError):
        await auth_module.ensure_fresh_access_token(session, install)

    assert install.status == "needs_reauth"
