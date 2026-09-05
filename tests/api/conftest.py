from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, Install
from app.db.session import get_session, get_session_factory
from app.main import app
from app.models.schemas import CanonicalRecord, PageResult, TokenSet
from app.models.schemas import WebhookEvent as WebhookEventSchema
from app.orchestration.registry import get_adapter


class FakeAdapter:
    """Fakes the ProviderAdapter Protocol end-to-end for API tests — per
    constitution.md §7, real HubSpot calls never happen in this suite."""

    provider_name = "fake"

    def __init__(self):
        self.exchange_result: TokenSet | None = None
        self.exchange_error: Exception | None = None
        self.refresh_result: TokenSet | None = None
        self.refresh_error: Exception | None = None
        self.pages: dict[str, list[PageResult]] = {}
        self._page_calls: dict[str, int] = {}
        self.fetch_one_result: CanonicalRecord | None = None
        self.fetch_one_error: Exception | None = None
        self.fetch_one_calls: list[tuple[str, str]] = []
        self.push_result: CanonicalRecord | None = None
        self.push_error: Exception | None = None
        self.push_calls: list[tuple[str, dict]] = []
        self.signature_valid = True
        self.parsed_events: list[WebhookEventSchema] = []

    async def build_authorize_url(self, state: str) -> str:
        return f"https://app.hubspot.com/oauth/authorize?state={state}"

    async def exchange_code_for_tokens(self, code: str) -> TokenSet:
        if self.exchange_error:
            raise self.exchange_error
        return self.exchange_result

    async def refresh_access_token(self, refresh_token: str) -> TokenSet:
        if self.refresh_error:
            raise self.refresh_error
        return self.refresh_result

    async def fetch_page(self, object_type: str, access_token: str, after: str | None) -> PageResult:
        pages = self.pages.get(object_type, [])
        idx = self._page_calls.get(object_type, 0)
        self._page_calls[object_type] = idx + 1
        if idx < len(pages):
            return pages[idx]
        return PageResult(records=[], next_after=None)

    async def fetch_one(self, object_type: str, access_token: str, object_id: str) -> CanonicalRecord:
        self.fetch_one_calls.append((object_type, object_id))
        if self.fetch_one_error:
            raise self.fetch_one_error
        return self.fetch_one_result

    async def push_record(
        self, object_type: str, access_token: str, record: CanonicalRecord
    ) -> CanonicalRecord:
        self.push_calls.append((object_type, record.properties))
        if self.push_error:
            raise self.push_error
        return self.push_result

    def verify_webhook_signature(self, method, request_uri, headers, raw_body) -> bool:
        return self.signature_valid

    def parse_webhook_events(self, raw_body: bytes) -> list[WebhookEventSchema]:
        return self.parsed_events


@pytest.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def fake_adapter():
    return FakeAdapter()


@pytest.fixture
def client(db_engine, fake_adapter):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    def override_get_adapter():
        return fake_adapter

    def override_get_session_factory():
        return session_factory

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_adapter] = override_get_adapter
    app.dependency_overrides[get_session_factory] = override_get_session_factory

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
async def seeded_install(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        install = Install(
            hub_id="12345",
            access_token="at-1",
            refresh_token="rt-1",
            access_token_expires_at=datetime.now(UTC) + timedelta(seconds=1700),
            scopes="oauth",
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(install)
        await session.commit()
        await session.refresh(install)
        return install


@pytest.fixture
async def seeded_install_near_expiry(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        install = Install(
            hub_id="99999",
            access_token="stale",
            refresh_token="dead-refresh-token",
            access_token_expires_at=datetime.now(UTC) + timedelta(seconds=10),
            scopes="oauth",
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(install)
        await session.commit()
        await session.refresh(install)
        return install


def make_page(external_id: str, object_type: str = "contacts") -> PageResult:
    return PageResult(
        records=[CanonicalRecord(external_id=external_id, object_type=object_type, properties={})],
        next_after=None,
    )
