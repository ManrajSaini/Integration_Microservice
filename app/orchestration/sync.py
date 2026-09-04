import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import ProviderAdapter
from app.db.models import Install, SyncRun
from app.db.repository import upsert_crm_record
from app.orchestration.auth import ensure_fresh_access_token
from app.orchestration.rate_limit import HUBSPOT_GENERAL_LIMIT, TokenBucket
from app.orchestration.retry import with_provider_retry

logger = logging.getLogger(__name__)

OBJECT_TYPES = ("contacts", "companies", "deals")


async def sync_object_type(
    session: AsyncSession,
    adapter: ProviderAdapter,
    install: Install,
    object_type: str,
    rate_limiter: TokenBucket = HUBSPOT_GENERAL_LIMIT,
) -> SyncRun:
    run = SyncRun(
        install_id=install.id,
        object_type=object_type,
        status="running",
        started_at=datetime.now(UTC),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    errors: list[dict] = []
    after: str | None = None

    while True:
        install = await ensure_fresh_access_token(session, install)

        await rate_limiter.acquire()
        page = await with_provider_retry(adapter.fetch_page)(
            object_type, install.access_token, after
        )

        for record in page.records:
            run.records_fetched += 1
            try:
                await upsert_crm_record(session, install.id, object_type, record)
                run.records_upserted += 1
            except Exception as exc:  # noqa: BLE001 - one bad record must not abort the run
                run.records_failed += 1
                errors.append({"hubspot_object_id": record.external_id, "error": str(exc)})
                logger.warning(
                    "Failed to upsert record during sync",
                    extra={"object_type": object_type, "external_id": record.external_id},
                )

        await session.commit()

        after = page.next_after
        if after is None:
            break

    run.status = "completed_with_errors" if errors else "completed"
    run.error_summary = errors or None
    run.finished_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(run)

    return run


async def run_sync(
    session: AsyncSession,
    adapter: ProviderAdapter,
    install: Install,
    object_types: list[str] | None = None,
) -> list[SyncRun]:
    types_to_sync = object_types or list(OBJECT_TYPES)
    runs = []
    for object_type in types_to_sync:
        run = await sync_object_type(session, adapter, install, object_type)
        runs.append(run)
    return runs
