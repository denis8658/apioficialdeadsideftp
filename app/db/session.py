from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()
engine_options = {
    "echo": settings.sql_echo,
    "pool_pre_ping": True,
    "pool_recycle": settings.database_pool_recycle_seconds,
}
if settings.database_url.startswith("postgresql"):
    engine_options.update({
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        "pool_timeout": settings.database_pool_timeout_seconds,
        "connect_args": {"command_timeout": settings.database_command_timeout_seconds},
    })
engine = create_async_engine(settings.database_url, **engine_options)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
