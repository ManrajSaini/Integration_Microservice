from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, Contact
from app.db.repository import upsert_crm_record, upsert_install
from app.models.schemas import CanonicalRecord, TokenSet


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as s:
        yield s

    await engine.dispose()


async def test_upsert_install_creates_then_updates_same_row(session):
    tokens = TokenSet(access_token="a1", refresh_token="r1", expires_in=1800, scopes=["oauth"])
    first = await upsert_install(session, hub_id="12345", tokens=tokens)

    tokens2 = TokenSet(access_token="a2", refresh_token="r1", expires_in=1800, scopes=["oauth"])
    second = await upsert_install(session, hub_id="12345", tokens=tokens2)

    assert first.id == second.id
    assert second.access_token == "a2"


async def test_upsert_crm_record_is_idempotent(session):
    tokens = TokenSet(access_token="a1", refresh_token="r1", expires_in=1800, scopes=["oauth"])
    install = await upsert_install(session, hub_id="12345", tokens=tokens)

    record = CanonicalRecord(
        external_id="999",
        object_type="contacts",
        properties={"email": "a@example.com", "firstname": "Ada"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    await upsert_crm_record(session, install.id, "contacts", record)
    await session.commit()

    updated_record = CanonicalRecord(
        external_id="999",
        object_type="contacts",
        properties={"email": "a@example.com", "firstname": "Ada Updated"},
        created_at=record.created_at,
        updated_at=datetime.now(UTC),
    )
    await upsert_crm_record(session, install.id, "contacts", updated_record)
    await session.commit()

    result = await session.execute(select(Contact).where(Contact.install_id == install.id))
    rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].firstname == "Ada Updated"
