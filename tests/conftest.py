"""Shared fixtures for link_shortener tests."""

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base
from app.dependencies import configure as configure_deps
from app.repositories.link_repository import LinkRepository
from app.services.link_service import LinkService


@pytest.fixture
async def db():
    """In-memory async SQLite engine with tables created via metadata."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(db):
    """Async session factory bound to the in-memory engine."""
    return async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def repository(session_factory):
    """LinkRepository backed by an in-memory database."""
    session = session_factory()
    repo = LinkRepository(session)
    yield repo
    await session.close()


@pytest.fixture
def service(repository):
    """LinkService with a real (in-memory) repository."""
    return LinkService(repository)


@asynccontextmanager
async def _test_lifespan(_app):
    """No-op lifespan for tests — DB + DI are set up by fixtures."""
    yield


@pytest.fixture
def app_client(repository, monkeypatch):
    """FastAPI TestClient with DI configured and test lifespan.

    Replaces the production lifespan so we don't hit Redis or file-based DB.
    The repository is injected via the fixture chain instead.
    """
    import main

    # Swap in a no-op lifespan to skip Redis + Alembic on startup.
    monkeypatch.setattr(main.app.router, "lifespan_context", _test_lifespan)

    svc = LinkService(repository)
    configure_deps(svc)

    with TestClient(main.app, raise_server_exceptions=True) as client:
        yield client

    # Cleanup: reset the global so other tests aren't affected.
    import app.dependencies

    app.dependencies._link_service = None
