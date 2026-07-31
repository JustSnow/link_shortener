"""Repository for link persistence — backed by SQLAlchemy + aiosqlite."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LinkORM
from app.models import Link


class LinkRepository:
    """Repository for link CRUD over an async SQLAlchemy session."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _to_domain(row: LinkORM) -> Link:
        return Link(id=row.id, original_url=row.original_url, created_at=row.created_at)

    # --- public API -------------------------------------------------------

    async def create(self, link: Link) -> Link:
        orm = LinkORM(id=link.id, original_url=link.original_url)
        self.session.add(orm)
        await self.session.commit()
        return link

    async def get_by_id(self, short_id: str) -> Link | None:
        row = await self.session.execute(select(LinkORM).where(LinkORM.id == short_id))
        result = row.scalar_one_or_none()
        if result is None:
            return None
        return self._to_domain(result)

    async def exists(self, short_id: str) -> bool:
        stmt = select(LinkORM.id).where(LinkORM.id == short_id)
        row = await self.session.execute(stmt)
        return row.scalar() is not None
