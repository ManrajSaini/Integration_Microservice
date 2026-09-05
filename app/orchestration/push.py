from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import ProviderAdapter
from app.db.models import Company, Contact, Deal, Install
from app.db.repository import get_crm_record, upsert_crm_record
from app.errors import NotFoundError
from app.models.schemas import CanonicalRecord
from app.orchestration.auth import ensure_fresh_access_token
from app.orchestration.rate_limit import HUBSPOT_GENERAL_LIMIT, TokenBucket
from app.orchestration.retry import with_provider_retry


async def push_local_changes(
    session: AsyncSession,
    adapter: ProviderAdapter,
    install: Install,
    object_type: str,
    hubspot_object_id: str,
    properties: dict,
    rate_limiter: TokenBucket = HUBSPOT_GENERAL_LIMIT,
) -> Contact | Company | Deal:
    """Bidirectional sync (bonus): push local property changes to HubSpot,
    then re-upsert locally from HubSpot's authoritative response — the same
    upsert path /sync and webhooks use, so the local row never drifts from
    what HubSpot actually stored."""
    existing = await get_crm_record(session, install.id, object_type, hubspot_object_id)
    if existing is None:
        raise NotFoundError(
            f"No local {object_type} record with hubspot_object_id={hubspot_object_id} "
            "— run /sync first so this service knows about it."
        )

    install = await ensure_fresh_access_token(session, adapter, install)

    outgoing = CanonicalRecord(
        external_id=hubspot_object_id, object_type=object_type, properties=properties
    )

    await rate_limiter.acquire()
    updated = await with_provider_retry(adapter.push_record)(
        object_type, install.access_token, outgoing
    )

    row = await upsert_crm_record(session, install.id, object_type, updated)
    await session.commit()
    await session.refresh(row)
    return row
