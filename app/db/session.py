from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Indirection so callers that need to open their own session outside a
    request (e.g. a background task) go through an overridable dependency
    instead of importing the module-level factory directly — tests override
    this the same way they override get_session/get_adapter."""
    return async_session_factory
