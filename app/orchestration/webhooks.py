import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import ProviderAdapter
from app.db.models import Install, WebhookEvent
from app.db.repository import get_install_by_hub_id, upsert_crm_record
from app.errors import ProviderError
from app.models.schemas import WebhookEvent as WebhookEventSchema
from app.orchestration.auth import ensure_fresh_access_token
from app.orchestration.rate_limit import HUBSPOT_GENERAL_LIMIT, TokenBucket
from app.orchestration.retry import with_provider_retry

logger = logging.getLogger(__name__)


async def persist_webhook_events(
    session: AsyncSession,
    events: list[WebhookEventSchema],
    signature_valid: bool,
) -> list[WebhookEvent]:
    """Persists every received event verbatim, regardless of dedup — the audit
    trail requirement. Resolves install_id from portal_id when possible.
    Caller commits."""
    rows = []
    for event in events:
        install = None
        if event.portal_id:
            install = await get_install_by_hub_id(session, event.portal_id)

        row = WebhookEvent(
            install_id=install.id if install else None,
            provider="hubspot",
            event_id=event.event_id,
            subscription_type=event.subscription_type,
            object_type=event.object_type,
            object_id=event.object_id,
            occurred_at=event.occurred_at,
            payload=event.raw,
            signature_valid=signature_valid,
            processed_at=None,
            processing_error=None,
            received_at=datetime.now(UTC),
        )
        session.add(row)
        rows.append(row)

    return rows


async def process_webhook_event(
    session: AsyncSession,
    adapter: ProviderAdapter,
    event_row_id: int,
    rate_limiter: TokenBucket = HUBSPOT_GENERAL_LIMIT,
) -> None:
    """Background task: re-fetch the current object state by objectId and
    upsert it via the same path Flow B (/sync) uses — architecture.md §4 Flow C
    step 4. Runs after the request has already returned 200 to HubSpot."""
    result = await session.execute(select(WebhookEvent).where(WebhookEvent.id == event_row_id))
    row = result.scalar_one_or_none()
    if row is None:
        return

    if row.object_type is None or row.install_id is None:
        row.processing_error = f"Unrecognized object type or unknown install for event {row.event_id}"
        row.processed_at = datetime.now(UTC)
        await session.commit()
        return

    object_type = row.object_type

    try:
        install = await _load_install(session, row.install_id)
        install = await ensure_fresh_access_token(session, adapter, install)

        await rate_limiter.acquire()
        record = await with_provider_retry(adapter.fetch_one)(
            object_type, install.access_token, row.object_id
        )
        await upsert_crm_record(session, install.id, object_type, record)

        row.processed_at = datetime.now(UTC)
        row.processing_error = None
    except ProviderError as exc:
        row.processed_at = datetime.now(UTC)
        row.processing_error = str(exc)
        logger.warning(
            "Failed to process webhook event",
            extra={"event_id": row.event_id, "object_id": row.object_id, "error": str(exc)},
        )
    finally:
        await session.commit()


async def _load_install(session: AsyncSession, install_id: int) -> Install:
    result = await session.execute(select(Install).where(Install.id == install_id))
    return result.scalar_one()
