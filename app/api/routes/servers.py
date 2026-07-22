import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import resolve_server
from app.db.models import Server
from app.db.session import get_session

router = APIRouter(prefix="/servers", tags=["servers"])


class ServerCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,118}[a-z0-9]$")
    name: str = Field(min_length=1, max_length=200)


class ServerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None


class ServerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    slug: str
    name: str
    enabled: bool


@router.get("", response_model=list[ServerOut])
async def list_servers(session: AsyncSession = Depends(get_session)):
    return (await session.scalars(select(Server).order_by(Server.name))).all()


@router.post("", response_model=ServerOut, status_code=status.HTTP_201_CREATED)
async def create_server(payload: ServerCreate, session: AsyncSession = Depends(get_session)):
    if await session.scalar(select(Server.id).where(Server.slug == payload.slug)):
        raise HTTPException(status_code=409, detail="server slug already exists")
    server = Server(**payload.model_dump())
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return server


@router.get("/{server_id}", response_model=ServerOut)
async def get_server(server_id: str, session: AsyncSession = Depends(get_session)):
    return await resolve_server(session, server_id)


@router.patch("/{server_id}", response_model=ServerOut)
async def patch_server(server_id: str, payload: ServerPatch, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(server, key, value)
    await session.commit()
    return server


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(server_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    await session.delete(server)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
