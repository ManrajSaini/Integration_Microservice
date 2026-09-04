from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, Contact, Install
from app.models.schemas import CanonicalRecord, PageResult
from app.orchestration.rate_limit import TokenBucket
from app.orchestration.sync import sync_object_type


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as s:
        yield s

    await engine.dispose()


@pytest.fixture
async def install(session):
    install = Install(
        hub_id="12345",
        access_token="fresh-token",
        refresh_token="refresh-1",
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


def _fast_limiter() -> TokenBucket:
    return TokenBucket(capacity=1000, period_seconds=0.01)


class FakeAdapter:
    """Fakes the ProviderAdapter Protocol's fetch_page for orchestration tests
    — per constitution.md §7, never mock httpx at this layer."""

    provider_name = "fake"

    def __init__(self, pages: list[PageResult]):
        self._pages = pages
        self.calls: list[str | None] = []

    async def fetch_page(self, object_type, access_token, after):
        self.calls.append(after)
        return self._pages[len(self.calls) - 1]


async def test_sync_object_type_paginates_until_next_after_is_none(session, install):
    pages = [
        PageResult(
            records=[
                CanonicalRecord(external_id="1", object_type="contacts", properties={"email": "a@x.com"})
            ],
            next_after="page-2",
        ),
        PageResult(
            records=[
                CanonicalRecord(external_id="2", object_type="contacts", properties={"email": "b@x.com"})
            ],
            next_after=None,
        ),
    ]
    adapter = FakeAdapter(pages)

    run = await sync_object_type(session, adapter, install, "contacts", rate_limiter=_fast_limiter())

    assert adapter.calls == [None, "page-2"]
    assert run.status == "completed"
    assert run.records_fetched == 2
    assert run.records_upserted == 2
    assert run.records_failed == 0

    result = await session.execute(select(Contact).where(Contact.install_id == install.id))
    assert len(result.scalars().all()) == 2


async def test_sync_object_type_one_bad_record_does_not_abort_run(session, install, monkeypatch):
    pages = [
        PageResult(
            records=[
                CanonicalRecord(external_id="1", object_type="contacts", properties={"email": "a@x.com"}),
                CanonicalRecord(external_id="2", object_type="contacts", properties={"email": "b@x.com"}),
            ],
            next_after=None,
        ),
    ]
    adapter = FakeAdapter(pages)

    import app.orchestration.sync as sync_module

    original_upsert = sync_module.upsert_crm_record

    async def flaky_upsert(session, install_id, object_type, record):
        if record.external_id == "1":
            raise ValueError("boom")
        return await original_upsert(session, install_id, object_type, record)

    monkeypatch.setattr(sync_module, "upsert_crm_record", flaky_upsert)

    run = await sync_object_type(session, adapter, install, "contacts", rate_limiter=_fast_limiter())

    assert run.status == "completed_with_errors"
    assert run.records_fetched == 2
    assert run.records_upserted == 1
    assert run.records_failed == 1
    assert run.error_summary == [{"hubspot_object_id": "1", "error": "boom"}]

    result = await session.execute(select(Contact).where(Contact.install_id == install.id))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].hubspot_object_id == "2"


async def test_sync_object_type_rerun_is_idempotent(session, install):
    pages = [
        PageResult(
            records=[
                CanonicalRecord(external_id="1", object_type="contacts", properties={"email": "a@x.com"})
            ],
            next_after=None,
        ),
    ]

    await sync_object_type(
        session, FakeAdapter(pages), install, "contacts", rate_limiter=_fast_limiter()
    )
    await sync_object_type(
        session, FakeAdapter(pages), install, "contacts", rate_limiter=_fast_limiter()
    )

    result = await session.execute(select(Contact).where(Contact.install_id == install.id))
    assert len(result.scalars().all()) == 1
