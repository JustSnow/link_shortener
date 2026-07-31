import aiosqlite

from app.models import Link


class LinkRepository:
    """Repository for link persistence over SQLite."""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def create(self, link: Link) -> Link:
        await self.db.execute(
            "INSERT INTO links (id, original_url) VALUES (?, ?)",
            (link.id, link.original_url),
        )
        await self.db.commit()
        return link

    async def get_by_id(self, short_id: str) -> Link | None:
        async with self.db.execute(
            "SELECT id, original_url, created_at FROM links WHERE id = ?",
            (short_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return Link(id=row[0], original_url=row[1], created_at=row[2])

    async def exists(self, short_id: str) -> bool:
        async with self.db.execute(
            "SELECT 1 FROM links WHERE id = ?", (short_id,)
        ) as cursor:
            return await cursor.fetchone() is not None
