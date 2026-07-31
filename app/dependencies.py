"""Dependency injection providers — no circular imports."""

from app.repositories.link_repository import LinkRepository
from app.services.link_service import LinkService


# Module-level singleton set during lifespan.
_link_service: LinkService | None = None


def configure(service: LinkService) -> None:
    global _link_service
    _link_service = service


def get_link_service() -> LinkService:
    if _link_service is None:
        raise RuntimeError("Application not started")
    return _link_service
