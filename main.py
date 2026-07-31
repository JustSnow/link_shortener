from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI

from app.dependencies import configure as configure_deps
from app.repositories.link_repository import LinkRepository
from app.routers.links import router as links_router
from app.services.link_service import LinkService

DB_PATH = "links.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiosqlite.connect(DB_PATH) as db:
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

        yield


app = FastAPI(lifespan=lifespan)
app.include_router(links_router)
