import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.db.session import get_session, get_session_factory
from app.orchestration.registry import ProviderAdapter, get_adapter
from app.orchestration.webhooks import persist_webhook_events, process_webhook_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])


async def _process_in_background(
    adapter: ProviderAdapter,
    session_factory: async_sessionmaker[AsyncSession],
    event_row_id: int,
) -> None:
    async with session_factory() as session:
        await process_webhook_event(session, adapter, event_row_id)


@router.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    adapter: ProviderAdapter = Depends(get_adapter),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> Response:
    raw_body = await request.body()
    # HubSpot signs the full public URL it was configured to POST to (the
    # app_base_url + path), not the path our server sees internally — this
    # matters whenever the public URL differs from how the request looks
    # locally (e.g. behind ngrok or any reverse proxy). See solve.md.
    request_uri = f"{settings.app_base_url.rstrip('/')}{request.url.path}"
    if request.url.query:
        request_uri += f"?{request.url.query}"

    signature_valid = adapter.verify_webhook_signature(
        method=request.method,
        request_uri=request_uri,
        headers=request.headers,
        raw_body=raw_body,
    )

    if not signature_valid:
        logger.warning("Rejected webhook request with invalid signature")
        return Response(status_code=401)

    events = adapter.parse_webhook_events(raw_body)
    rows = await persist_webhook_events(session, events, signature_valid=True)
    await session.commit()
    for row in rows:
        await session.refresh(row)

    for row in rows:
        background_tasks.add_task(_process_in_background, adapter, session_factory, row.id)

    return Response(status_code=200)
