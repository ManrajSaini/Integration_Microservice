import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Contact, WebhookEvent
from app.db.repository import upsert_crm_record
from app.models.schemas import CanonicalRecord
from app.models.schemas import WebhookEvent as WebhookEventSchema


def _event(
    event_id="1",
    subscription_type="object.propertyChange",
    object_type="contacts",
    object_id="999",
    portal_id="12345",
):
    return WebhookEventSchema(
        event_id=event_id,
        subscription_type=subscription_type,
        object_type=object_type,
        object_id=object_id,
        occurred_at=datetime.now(UTC),
        portal_id=portal_id,
        raw={"eventId": event_id, "objectId": object_id, "subscriptionType": subscription_type},
    )


def test_webhook_invalid_signature_returns_401_and_persists_nothing(client, fake_adapter, db_engine):
    fake_adapter.signature_valid = False
    fake_adapter.parsed_events = [_event()]

    response = client.post("/webhook", content=b'[{"eventId":"1"}]')

    assert response.status_code == 401


async def _count_webhook_events(db_engine) -> int:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(select(WebhookEvent))
        return len(result.scalars().all())


def test_webhook_valid_signature_persists_event_and_returns_200(client, fake_adapter, db_engine, seeded_install):
    fake_adapter.signature_valid = True
    fake_adapter.parsed_events = [_event(portal_id="12345")]
    fake_adapter.fetch_one_result = CanonicalRecord(
        external_id="999", object_type="contacts", properties={"email": "a@example.com"}
    )

    response = client.post("/webhook", content=b'[{"eventId":"1"}]')

    assert response.status_code == 200
    count = asyncio.get_event_loop().run_until_complete(_count_webhook_events(db_engine))
    assert count == 1


def test_webhook_persists_event_even_when_portal_unknown(client, fake_adapter, db_engine):
    fake_adapter.signature_valid = True
    fake_adapter.parsed_events = [_event(portal_id="unknown-portal")]

    response = client.post("/webhook", content=b'[{"eventId":"1"}]')

    assert response.status_code == 200
    count = asyncio.get_event_loop().run_until_complete(_count_webhook_events(db_engine))
    assert count == 1


async def _get_contact(db_engine, hubspot_object_id: str) -> Contact | None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(
            select(Contact).where(Contact.hubspot_object_id == hubspot_object_id)
        )
        return result.scalar_one_or_none()


def test_webhook_background_processing_upserts_contact(client, fake_adapter, db_engine, seeded_install):
    fake_adapter.signature_valid = True
    fake_adapter.parsed_events = [_event(object_id="999", portal_id="12345")]
    fake_adapter.fetch_one_result = CanonicalRecord(
        external_id="999", object_type="contacts", properties={"email": "webhook@example.com"}
    )

    response = client.post("/webhook", content=b'[{"eventId":"1"}]')

    assert response.status_code == 200
    assert fake_adapter.fetch_one_calls == [("contacts", "999")]

    contact = asyncio.get_event_loop().run_until_complete(_get_contact(db_engine, "999"))
    assert contact is not None
    assert contact.email == "webhook@example.com"


async def _seed_existing_contact(db_engine, install_id: int) -> None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        record = CanonicalRecord(
            external_id="999", object_type="contacts", properties={"email": "before@example.com"}
        )
        await upsert_crm_record(session, install_id, "contacts", record)
        await session.commit()


def test_webhook_updates_existing_contact_without_sync(client, fake_adapter, db_engine, seeded_install):
    """Phase 8's core scenario: a contact already synced once (e.g. via a
    prior /sync) gets edited in HubSpot — the webhook alone, with no /sync
    call, must bring the local row up to date. See architecture.md §4 Flow C."""
    asyncio.get_event_loop().run_until_complete(_seed_existing_contact(db_engine, seeded_install.id))

    before = asyncio.get_event_loop().run_until_complete(_get_contact(db_engine, "999"))
    assert before.email == "before@example.com"

    fake_adapter.signature_valid = True
    fake_adapter.parsed_events = [_event(object_id="999", portal_id="12345")]
    fake_adapter.fetch_one_result = CanonicalRecord(
        external_id="999", object_type="contacts", properties={"email": "after@example.com"}
    )

    response = client.post("/webhook", content=b'[{"eventId":"1"}]')

    assert response.status_code == 200

    after = asyncio.get_event_loop().run_until_complete(_get_contact(db_engine, "999"))
    assert after.id == before.id  # same row updated in place, not duplicated
    assert after.email == "after@example.com"
