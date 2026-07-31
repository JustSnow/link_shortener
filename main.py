import os
from contextlib import asynccontextmanager

import aiosqlite
import redis.asyncio as redis
from fastapi import FastAPI

from app.dependencies import configure as configure_deps
from app.middleware import RateLimiterMiddleware
from app.repositories.link_repository import LinkRepository
from app.routers.links import router as links_router
from app.services.link_service import LinkService

DB_PATH = "links.db"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- SQLite setup ---
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                id TEXT PRIMARY KEY,
                original_url TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.commit()

        repo = LinkRepository(db)
        configure_deps(LinkService(repo))

        # --- Redis setup (rate limiter) ---
        app.state.redis_client = redis.from_url(
            REDIS_URL, decode_responses=True
        )

        yield
    finally:
        await db.close()
        await app.state.redis_client.aclose()


app = FastAPI(lifespan=lifespan)
# Rate-limiter middleware — accesses app.state.redis_client lazily at request time
app.add_middleware(RateLimiterMiddleware, fastapi_app=app)
app.include_router(links_router)
