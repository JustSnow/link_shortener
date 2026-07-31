"""Shared fixtures for link_shortener tests."""

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from app.dependencies import configure as configure_deps
from app.repositories.link_repository import LinkRepository
from app.services.link_service import LinkService


@pytest.fixture
async def db():
    """In-memory SQLite database with the links table."""
    async with aiosqlite.connect(":memory:") as conn:
        await conn.execute(
            """
            CREATE TABLE links (
                id TEXT PRIMARY KEY,
                original_url TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.commit()
        yield conn


@pytest.fixture
async def repository(db):
    """LinkRepository backed by an in-memory database."""
    return LinkRepository(db)


@pytest.fixture
def service(repository):
    """LinkService with a real (in-memory) repository."""
    return LinkService(repository)


@pytest.fixture
def app_client(db, repository):
    """FastAPI TestClient with the DI singleton configured."""
    svc = LinkService(repository)
    configure_deps(svc)

    # Patch lifespan to yield nothing extra — DB is already set up.
    from main import app

    with TestClient(app) as client:
        yield client

    # Cleanup: reset the global so other tests aren't affected.
    import app.dependencies

    app.dependencies._link_service = None
