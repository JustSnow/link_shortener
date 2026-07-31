import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI

from alembic import command as alembic_command
from app.db import create_engine, create_session_factory
from app.dependencies import configure as configure_deps
from app.middleware import RateLimiterMiddleware
from app.repositories.link_repository import LinkRepository
from app.routers.links import router as links_router
from app.services.link_service import LinkService

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _run_migrations() -> None:
    """Apply all pending Alembic migrations on startup."""
    alembic_cfg = AlembicConfig("alembic.ini")
    alembic_command.upgrade(alembic_cfg, "head")


@asynccontextmanager
async def lifespan(application: FastAPI):
    engine = create_engine()
    session_factory = create_session_factory(engine)

    # Run Alembic migrations before anything else touches the DB.
    _run_migrations()

    repo = LinkRepository(session_factory())
    configure_deps(LinkService(repo))

    application.state.redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

    yield

    await repo.session.close()
    await engine.dispose()
    await application.state.redis_client.aclose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(RateLimiterMiddleware, fastapi_app=app)
app.include_router(links_router)
