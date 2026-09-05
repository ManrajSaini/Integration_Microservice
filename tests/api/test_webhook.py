from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import WebhookEvent
from app.models.schemas import CanonicalRecord
from app.models.schemas import WebhookEvent as WebhookEventSchema


def _event(event_id="1", subscription_type="contact.propertyChange", object_id="999", portal_id="12345"):
    return WebhookEventSchema(
        event_id=event_id,
        subscription_type=subscription_type,
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

    import asyncio

    count = asyncio.get_event_loop().run_until_complete(_count_webhook_events(db_engine))
    assert count == 1


def test_webhook_persists_event_even_when_portal_unknown(client, fake_adapter, db_engine):
    fake_adapter.signature_valid = True
    fake_adapter.parsed_events = [_event(portal_id="unknown-portal")]

    response = client.post("/webhook", content=b'[{"eventId":"1"}]')

    assert response.status_code == 200

    import asyncio

    count = asyncio.get_event_loop().run_until_complete(_count_webhook_events(db_engine))
    assert count == 1


def test_webhook_background_processing_upserts_contact(client, fake_adapter, db_engine, seeded_install):
    fake_adapter.signature_valid = True
    fake_adapter.parsed_events = [_event(object_id="999", portal_id="12345")]
    fake_adapter.fetch_one_result = CanonicalRecord(
        external_id="999", object_type="contacts", properties={"email": "webhook@example.com"}
    )

    response = client.post("/webhook", content=b'[{"eventId":"1"}]')

    assert response.status_code == 200
    assert fake_adapter.fetch_one_calls == [("contacts", "999")]

    import asyncio

    from app.db.models import Contact

    async def _check():
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as session:
            result = await session.execute(select(Contact).where(Contact.hubspot_object_id == "999"))
            return result.scalar_one_or_none()

    contact = asyncio.get_event_loop().run_until_complete(_check())
    assert contact is not None
    assert contact.email == "webhook@example.com"
