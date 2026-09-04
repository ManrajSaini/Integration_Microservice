from fastapi import FastAPI

from app.logging import configure_logging

configure_logging()

app = FastAPI(title="Integration Microservice")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
