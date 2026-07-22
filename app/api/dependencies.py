import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Server


async def resolve_server(session: AsyncSession, identifier: str) -> Server:
    condition = Server.slug == identifier
    try:
        condition = (Server.id == uuid.UUID(identifier)) | condition
    except ValueError:
        pass
    server = await session.scalar(select(Server).where(condition))
    if server is None:
        raise HTTPException(status_code=404, detail="server not found")
    return server
