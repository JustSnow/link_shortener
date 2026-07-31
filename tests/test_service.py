"""Unit tests for LinkService."""

import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import Link, ShortenRequest, ShortenResponse
from app.services.link_service import LinkService


class TestGenerateKey:
    def test_key_length(self):
        key = LinkService._generate_key()
        assert len(key) == 6

    def test_key_charset(self):
        key = LinkService._generate_key()
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        assert all(c in allowed for c in key)


class TestShorten:
    @pytest.mark.asyncio
    async def test_shorten_creates_link(self):
        repo = AsyncMock()
        repo.exists = AsyncMock(return_value=False)
        repo.create = AsyncMock()

        svc = LinkService(repo)
        request = ShortenRequest(url="https://example.com")
        response = await svc.shorten(request)

        assert isinstance(response, ShortenResponse)
        assert "/s/" in response.short_url
        repo.create.assert_called_once()
        created_link = repo.create.call_args[0][0]
        assert isinstance(created_link, Link)
        assert created_link.original_url.startswith("https://example.com")

    @pytest.mark.asyncio
    async def test_shorten_retries_on_collision(self):
        """When a generated key already exists, service regenerates until unique."""
        repo = AsyncMock()
        # First two keys collide, third is free.
        repo.exists = AsyncMock(side_effect=[True, True, False])
        repo.create = AsyncMock()

        svc = LinkService(repo)
        # Deterministic keys for predictability.
        deterministic_keys = iter(["AAA", "BBB", "CCC"])
        original_choices = random.choices

        def fake_choices(population, k):
            return list(deterministic_keys.__next__())

        random.choices = fake_choices  # type: ignore

        try:
            await svc.shorten(ShortenRequest(url="https://example.com"))
        finally:
            random.choices = original_choices

        assert repo.exists.call_count == 3


class TestGetOriginalUrl:
    @pytest.mark.asyncio
    async def test_returns_url_when_found(self):
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=Link(id="abc", original_url="https://example.com"))

        svc = LinkService(repo)
        url = await svc.get_original_url("abc")

        assert url == "https://example.com"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=None)

        svc = LinkService(repo)
        url = await svc.get_original_url("nonexistent")

        assert url is None
