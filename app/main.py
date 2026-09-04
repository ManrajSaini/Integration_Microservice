from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.oauth import router as oauth_router
from app.api.sync import router as sync_router
from app.logging import configure_logging

configure_logging()

app = FastAPI(title="Integration Microservice")

register_exception_handlers(app)
app.include_router(oauth_router)
app.include_router(sync_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
