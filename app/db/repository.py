from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, Contact, Deal, Install
from app.models.schemas import CanonicalRecord, TokenSet

_CRM_MODELS: dict[str, type[Contact] | type[Company] | type[Deal]] = {
    "contacts": Contact,
    "companies": Company,
    "deals": Deal,
}

# Promoted (indexed) columns pulled out of `properties` for each object type,
# per architecture.md §3.
_PROMOTED_FIELDS: dict[str, tuple[str, ...]] = {
    "contacts": ("email", "firstname", "lastname", "lifecyclestage"),
    "companies": ("name", "domain"),
    "deals": ("dealname", "dealstage", "amount", "pipeline"),
}


async def get_install_by_hub_id(session: AsyncSession, hub_id: str) -> Install | None:
    result = await session.execute(select(Install).where(Install.hub_id == hub_id))
    return result.scalar_one_or_none()


async def upsert_install(session: AsyncSession, hub_id: str, tokens: TokenSet) -> Install:
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=tokens.expires_in)
    install = await get_install_by_hub_id(session, hub_id)

    if install is None:
        install = Install(
            hub_id=hub_id,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            access_token_expires_at=expires_at,
            scopes=" ".join(tokens.scopes),
            status="active",
            created_at=now,
            updated_at=now,
        )
        session.add(install)
    else:
        install.access_token = tokens.access_token
        install.refresh_token = tokens.refresh_token
        install.access_token_expires_at = expires_at
        install.scopes = " ".join(tokens.scopes)
        install.status = "active"
        install.updated_at = now

    await session.commit()
    await session.refresh(install)
    return install


async def upsert_crm_record(
    session: AsyncSession, install_id: int, object_type: str, record: CanonicalRecord
) -> Contact | Company | Deal:
    model = _CRM_MODELS[object_type]
    result = await session.execute(
        select(model).where(
            model.install_id == install_id,
            model.hubspot_object_id == record.external_id,
        )
    )
    row = result.scalar_one_or_none()

    promoted = {
        field: record.properties.get(field) for field in _PROMOTED_FIELDS[object_type]
    }
    now = datetime.now(UTC)

    if row is None:
        row = model(
            install_id=install_id,
            hubspot_object_id=record.external_id,
            properties=record.properties,
            hs_created_at=record.created_at,
            hs_updated_at=record.updated_at,
            archived=record.archived,
            synced_at=now,
            **promoted,
        )
        session.add(row)
    else:
        row.properties = record.properties
        row.hs_created_at = record.created_at
        row.hs_updated_at = record.updated_at
        row.archived = record.archived
        row.synced_at = now
        for field, value in promoted.items():
            setattr(row, field, value)

    return row
