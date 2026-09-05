import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Contact
from app.db.repository import upsert_crm_record
from app.errors import ConflictError
from app.models.schemas import CanonicalRecord


async def _seed_contact(db_engine, install_id: int) -> None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        record = CanonicalRecord(
            external_id="999", object_type="contacts", properties={"email": "before@example.com"}
        )
        await upsert_crm_record(session, install_id, "contacts", record)
        await session.commit()


async def _get_contact(db_engine) -> Contact | None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(select(Contact).where(Contact.hubspot_object_id == "999"))
        return result.scalar_one_or_none()


def test_push_contact_not_synced_returns_404(client, seeded_install):
    response = client.patch(
        "/contacts/999",
        json={"hub_id": "12345", "properties": {"email": "new@example.com"}},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_push_contact_unknown_hub_id_returns_404(client):
    response = client.patch(
        "/contacts/999",
        json={"hub_id": "does-not-exist", "properties": {"email": "new@example.com"}},
    )

    assert response.status_code == 404


def test_push_contact_updates_hubspot_and_local_row(client, fake_adapter, db_engine, seeded_install):
    asyncio.get_event_loop().run_until_complete(_seed_contact(db_engine, seeded_install.id))

    fake_adapter.push_result = CanonicalRecord(
        external_id="999", object_type="contacts", properties={"email": "after@example.com"}
    )

    response = client.patch(
        "/contacts/999",
        json={"hub_id": "12345", "properties": {"email": "after@example.com"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["properties"]["email"] == "after@example.com"

    assert fake_adapter.push_calls == [("contacts", {"email": "after@example.com"})]

    contact = asyncio.get_event_loop().run_until_complete(_get_contact(db_engine))
    assert contact.email == "after@example.com"


def test_push_contact_hubspot_conflict_returns_409_envelope(client, fake_adapter, db_engine, seeded_install):
    asyncio.get_event_loop().run_until_complete(_seed_contact(db_engine, seeded_install.id))
    fake_adapter.push_error = ConflictError("Contact already exists. Existing ID: 555")

    response = client.patch(
        "/contacts/999",
        json={"hub_id": "12345", "properties": {"email": "dup@example.com"}},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
