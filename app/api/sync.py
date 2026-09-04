from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import get_install_by_hub_id
from app.db.session import get_session
from app.errors import NotFoundError, ValidationError
from app.orchestration.registry import ProviderAdapter, get_adapter
from app.orchestration.sync import OBJECT_TYPES, run_sync

router = APIRouter(tags=["sync"])


class SyncRequest(BaseModel):
    hub_id: str
    object_types: list[str] | None = None


class SyncRunResponse(BaseModel):
    object_type: str
    status: str
    records_fetched: int
    records_upserted: int
    records_failed: int


@router.post("/sync")
async def sync(
    request: SyncRequest,
    session: AsyncSession = Depends(get_session),
    adapter: ProviderAdapter = Depends(get_adapter),
) -> list[SyncRunResponse]:
    install = await get_install_by_hub_id(session, request.hub_id)
    if install is None:
        raise NotFoundError(f"No install found for hub_id={request.hub_id}")

    object_types = request.object_types or list(OBJECT_TYPES)
    invalid = set(object_types) - set(OBJECT_TYPES)
    if invalid:
        raise ValidationError(f"Unknown object_types: {sorted(invalid)}")

    runs = await run_sync(session, adapter, install, object_types)

    return [
        SyncRunResponse(
            object_type=run.object_type,
            status=run.status,
            records_fetched=run.records_fetched,
            records_upserted=run.records_upserted,
            records_failed=run.records_failed,
        )
        for run in runs
    ]
