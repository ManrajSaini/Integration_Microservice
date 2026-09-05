from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import get_install_by_hub_id, list_crm_records
from app.db.session import get_session
from app.errors import NotFoundError
from app.orchestration.push import push_local_changes
from app.orchestration.registry import ProviderAdapter, get_adapter

router = APIRouter(tags=["crm"])

# Query params accepted per object type, beyond the shared sort/limit/offset —
# mirrors the promoted columns in architecture.md §3.
_FILTERABLE_PARAMS: dict[str, tuple[str, ...]] = {
    "contacts": ("email", "firstname", "lastname", "lifecyclestage"),
    "companies": ("name", "domain"),
    "deals": ("dealname", "dealstage", "amount", "pipeline"),
}


async def _list_object_type(
    object_type: str,
    session: AsyncSession,
    query_params: dict[str, str],
    sort: str | None,
    limit: int,
    offset: int,
) -> list[dict]:
    allowed = _FILTERABLE_PARAMS[object_type]
    filters = {k: v for k, v in query_params.items() if k in allowed and v is not None}

    rows = await list_crm_records(
        session, object_type, filters=filters, sort=sort, limit=limit, offset=offset
    )
    return [
        {
            "id": row.hubspot_object_id,
            "properties": row.properties,
            "created_at": row.hs_created_at,
            "updated_at": row.hs_updated_at,
            "archived": row.archived,
        }
        for row in rows
    ]


@router.get("/contacts")
async def list_contacts(
    email: str | None = None,
    firstname: str | None = None,
    lastname: str | None = None,
    lifecyclestage: str | None = None,
    sort: str | None = Query(default=None, description="e.g. updated_at or -updated_at"),
    limit: int = Query(default=50, le=100, gt=0),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    return await _list_object_type(
        "contacts",
        session,
        {"email": email, "firstname": firstname, "lastname": lastname, "lifecyclestage": lifecyclestage},
        sort,
        limit,
        offset,
    )


@router.get("/companies")
async def list_companies(
    name: str | None = None,
    domain: str | None = None,
    sort: str | None = Query(default=None, description="e.g. updated_at or -updated_at"),
    limit: int = Query(default=50, le=100, gt=0),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    return await _list_object_type(
        "companies", session, {"name": name, "domain": domain}, sort, limit, offset
    )


@router.get("/deals")
async def list_deals(
    dealname: str | None = None,
    dealstage: str | None = None,
    amount: str | None = None,
    pipeline: str | None = None,
    sort: str | None = Query(default=None, description="e.g. updated_at or -updated_at"),
    limit: int = Query(default=50, le=100, gt=0),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    return await _list_object_type(
        "deals",
        session,
        {"dealname": dealname, "dealstage": dealstage, "amount": amount, "pipeline": pipeline},
        sort,
        limit,
        offset,
    )


class PushRequest(BaseModel):
    hub_id: str
    properties: dict[str, str | None]


async def _push_object_type(
    object_type: str,
    hubspot_object_id: str,
    request: PushRequest,
    session: AsyncSession,
    adapter: ProviderAdapter,
) -> dict:
    install = await get_install_by_hub_id(session, request.hub_id)
    if install is None:
        raise NotFoundError(f"No install found for hub_id={request.hub_id}")

    row = await push_local_changes(
        session, adapter, install, object_type, hubspot_object_id, request.properties
    )
    return {
        "id": row.hubspot_object_id,
        "properties": row.properties,
        "created_at": row.hs_created_at,
        "updated_at": row.hs_updated_at,
        "archived": row.archived,
    }


@router.patch("/contacts/{hubspot_object_id}")
async def push_contact(
    hubspot_object_id: str,
    request: PushRequest,
    session: AsyncSession = Depends(get_session),
    adapter: ProviderAdapter = Depends(get_adapter),
) -> dict:
    return await _push_object_type("contacts", hubspot_object_id, request, session, adapter)


@router.patch("/companies/{hubspot_object_id}")
async def push_company(
    hubspot_object_id: str,
    request: PushRequest,
    session: AsyncSession = Depends(get_session),
    adapter: ProviderAdapter = Depends(get_adapter),
) -> dict:
    return await _push_object_type("companies", hubspot_object_id, request, session, adapter)


@router.patch("/deals/{hubspot_object_id}")
async def push_deal(
    hubspot_object_id: str,
    request: PushRequest,
    session: AsyncSession = Depends(get_session),
    adapter: ProviderAdapter = Depends(get_adapter),
) -> dict:
    return await _push_object_type("deals", hubspot_object_id, request, session, adapter)
