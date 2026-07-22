import asyncio

from sqlalchemy import select

from app.db.models import Server
from app.db.session import SessionLocal


async def main() -> None:
    async with SessionLocal() as session:
        if not await session.scalar(select(Server.id).where(Server.slug == "deadside-local")):
            session.add(Server(slug="deadside-local", name="Deadside Local"))
            await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
