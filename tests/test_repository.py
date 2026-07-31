"""Integration tests for LinkRepository (in-memory SQLite)."""

import pytest

from app.models import Link


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_persists_link(self, repository):
        link = Link(id="abc123", original_url="https://example.com")
        result = await repository.create(link)

        assert result.id == "abc123"
        assert result.original_url == "https://example.com"


class TestGetById:
    @pytest.mark.asyncio
    async def test_get_by_id_returns_link(self, repository):
        link = Link(id="xyz789", original_url="https://test.com")
        await repository.create(link)

        found = await repository.get_by_id("xyz789")

        assert found is not None
        assert found.id == "xyz789"
        assert found.original_url == "https://test.com"
        assert found.created_at is not None

    @pytest.mark.asyncio
    async def test_get_by_id_returns_none(self, repository):
        found = await repository.get_by_id("does-not-exist")
        assert found is None


class TestExists:
    @pytest.mark.asyncio
    async def test_exists_true(self, repository):
        await repository.create(Link(id="exists1", original_url="https://a.com"))
        assert await repository.exists("exists1") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, repository):
        assert await repository.exists("nope") is False
