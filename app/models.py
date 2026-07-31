from datetime import datetime

from pydantic import BaseModel, HttpUrl


class Link(BaseModel):
    """Domain entity representing a shortened link."""

    id: str
    original_url: str
    created_at: datetime | None = None


class ShortenRequest(BaseModel):
    url: HttpUrl


class ShortenResponse(BaseModel):
    short_url: str
