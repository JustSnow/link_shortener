import random
import string

from app.models import Link, ShortenRequest, ShortenResponse
from app.repositories.link_repository import LinkRepository

CHARS = string.ascii_letters + string.digits
KEY_LEN = 6


class LinkService:
    """Business logic for link shortening."""

    def __init__(self, repository: LinkRepository):
        self.repository = repository

    @staticmethod
    def _generate_key() -> str:
        return "".join(random.choices(CHARS, k=KEY_LEN))

    async def shorten(self, request: ShortenRequest) -> ShortenResponse:
        key = self._generate_key()
        while await self.repository.exists(key):
            key = self._generate_key()

        link = Link(id=key, original_url=str(request.url))
        await self.repository.create(link)
        return ShortenResponse(short_url=f"http://localhost:8000/s/{key}")

    async def get_original_url(self, short_id: str) -> str | None:
        link = await self.repository.get_by_id(short_id)
        if link is None:
            return None
        return link.original_url
