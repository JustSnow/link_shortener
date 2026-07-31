"""Database engine and session factory."""

import aiosqlite  # noqa: F401 — registered as async driver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DB_PATH = "links.db"


def create_engine(db_url: str | None = None) -> object:
    """Create an async SQLAlchemy engine pointing at SQLite."""
    url = db_url or f"sqlite+aiosqlite:///{DB_PATH}"
    return create_async_engine(url, echo=False)


def create_session_factory(engine: object) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
