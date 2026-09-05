from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.repository import list_crm_records, upsert_crm_record, upsert_install
from app.errors import ValidationError
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


@pytest.fixture
async def install_id(session):
    tokens = TokenSet(
        access_token="a1", refresh_token="r1", expires_in=1800, scopes=["oauth"], account_id="12345"
    )
    install = await upsert_install(session, hub_id="12345", tokens=tokens)
    await session.commit()
    return install.id


async def _seed_contacts(session, install_id):
    base_time = datetime.now(UTC)
    contacts = [
        ("1", "ada@example.com", "Ada", base_time),
        ("2", "bob@example.com", "Bob", base_time + timedelta(minutes=1)),
        ("3", "carl@example.com", "Carl", base_time + timedelta(minutes=2)),
    ]
    for external_id, email, firstname, updated_at in contacts:
        record = CanonicalRecord(
            external_id=external_id,
            object_type="contacts",
            properties={"email": email, "firstname": firstname},
            created_at=base_time,
            updated_at=updated_at,
        )
        await upsert_crm_record(session, install_id, "contacts", record)
    await session.commit()


async def test_filter_by_promoted_field(session, install_id):
    await _seed_contacts(session, install_id)

    rows = await list_crm_records(session, "contacts", filters={"email": "bob@example.com"})

    assert len(rows) == 1
    assert rows[0].firstname == "Bob"


async def test_sort_by_updated_at_alias_ascending(session, install_id):
    await _seed_contacts(session, install_id)

    rows = await list_crm_records(session, "contacts", sort="updated_at")

    assert [r.firstname for r in rows] == ["Ada", "Bob", "Carl"]


async def test_sort_by_updated_at_alias_descending(session, install_id):
    await _seed_contacts(session, install_id)

    rows = await list_crm_records(session, "contacts", sort="-updated_at")

    assert [r.firstname for r in rows] == ["Carl", "Bob", "Ada"]


async def test_filter_by_non_promoted_field_raises_validation_error(session, install_id):
    await _seed_contacts(session, install_id)

    with pytest.raises(ValidationError):
        await list_crm_records(session, "contacts", filters={"not_a_real_field": "x"})


async def test_sort_by_unknown_field_raises_validation_error(session, install_id):
    await _seed_contacts(session, install_id)

    with pytest.raises(ValidationError):
        await list_crm_records(session, "contacts", sort="not_a_real_field")


async def test_limit_and_offset(session, install_id):
    await _seed_contacts(session, install_id)

    rows = await list_crm_records(session, "contacts", sort="updated_at", limit=1, offset=1)

    assert len(rows) == 1
    assert rows[0].firstname == "Bob"
