from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.orchestration.auth import complete_install, start_install

router = APIRouter(prefix="/oauth", tags=["oauth"])


@router.get("/authorize")
async def authorize() -> RedirectResponse:
    url = await start_install()
    return RedirectResponse(url)


@router.get("/callback")
async def callback(code: str, state: str, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    hub_id = await complete_install(session, code=code, state=state)
    return {"status": "installed", "hub_id": hub_id}
