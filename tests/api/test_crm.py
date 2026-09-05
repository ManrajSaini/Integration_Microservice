from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.repository import upsert_crm_record
from app.models.schemas import CanonicalRecord


@pytest.fixture
async def seeded_contacts(db_engine, seeded_install):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    base_time = datetime.now(UTC)
    async with session_factory() as session:
        for i, (email, firstname) in enumerate(
            [("ada@example.com", "Ada"), ("bob@example.com", "Bob")]
        ):
            record = CanonicalRecord(
                external_id=str(i + 1),
                object_type="contacts",
                properties={"email": email, "firstname": firstname},
                created_at=base_time,
                updated_at=base_time + timedelta(minutes=i),
            )
            await upsert_crm_record(session, seeded_install.id, "contacts", record)
        await session.commit()


def test_list_contacts_returns_seeded_rows(client, seeded_contacts):
    response = client.get("/contacts")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2


def test_list_contacts_filter_by_email(client, seeded_contacts):
    response = client.get("/contacts", params={"email": "bob@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["properties"]["firstname"] == "Bob"


def test_list_contacts_sort_updated_at_descending(client, seeded_contacts):
    response = client.get("/contacts", params={"sort": "-updated_at"})

    assert response.status_code == 200
    body = response.json()
    assert [r["properties"]["firstname"] for r in body] == ["Bob", "Ada"]


def test_list_contacts_invalid_sort_field_returns_400_envelope(client, seeded_install):
    response = client.get("/contacts", params={"sort": "not_a_real_field"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_companies_empty_by_default(client, seeded_install):
    response = client.get("/companies")

    assert response.status_code == 200
    assert response.json() == []


def test_list_deals_empty_by_default(client, seeded_install):
    response = client.get("/deals")

    assert response.status_code == 200
    assert response.json() == []
