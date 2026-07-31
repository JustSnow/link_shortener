"""Tests for Redis-backed sliding-log rate limiter middleware."""

import asyncio
from contextlib import asynccontextmanager

import pytest
import redis.asyncio as aioredis
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.middleware import RateLimiterMiddleware


# ---------------------------------------------------------------------------
# Auto-skip the whole module when Redis is not reachable.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _require_redis():
    """Fail early with a skip if Redis cannot be reached."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect(("127.0.0.1", 6379))
    except OSError:
        pytest.skip("Redis not running — start via `docker compose up -d`")
    finally:
        sock.close()


@pytest.fixture()
async def redis_client():
    """Connect to local Redis (started via docker-compose)."""
    client = aioredis.from_url("redis://localhost:6379/0", decode_responses=True)
    yield client
    await client.flushdb()
    await client.close()


@pytest.fixture()
def app(redis_client):
    """Minimal FastAPI app with rate limiter middleware."""

    @asynccontextmanager
    async def lifespan(a: FastAPI):
        a.state.redis_client = redis_client
        yield

    test_app = FastAPI(lifespan=lifespan)

    @test_app.post("/shorten")
    async def shorten():
        return {"ok": True}

    @test_app.get("/other")
    async def other():
        return {"ok": True}

    test_app.add_middleware(
        RateLimiterMiddleware, fastapi_app=test_app, max_requests=5, window_seconds=60
    )
    return test_app


@pytest.fixture()
def client(app):
    return TestClient(app)


class TestRateLimiter:
    """Verify sliding-log rate limiting behaviour."""

    def test_allows_up_to_limit(self, client):
        for _ in range(5):
            resp = client.post("/shorten", json={"url": "https://example.com"})
            assert resp.status_code == 200

    def test_blocks_when_exceeding_limit(self, client):
        # Exhaust the limit
        for _ in range(5):
            client.post("/shorten", json={"url": "https://example.com"})

        # Next request should be rate-limited
        resp = client.post("/shorten", json={"url": "https://example.com"})
        assert resp.status_code == 429
        assert "Rate limit exceeded" in resp.json()["detail"]

    def test_non_shorten_endpoint_not_limited(self, client):
        """GET /other should never be rate-limited."""
        for _ in range(100):
            resp = client.get("/other")
            assert resp.status_code == 200

    def test_rate_limit_headers_present(self, client):
        resp = client.post("/shorten", json={"url": "https://example.com"})
        assert resp.status_code == 200
        assert resp.headers["X-RateLimit-Limit"] == "5"
        assert resp.headers["X-RateLimit-Remaining"] == "4"

    def test_remaining_decrements(self, client):
        for expected in range(4, -1, -1):
            resp = client.post("/shorten", json={"url": "https://example.com"})
            assert resp.status_code == 200
            assert resp.headers["X-RateLimit-Remaining"] == str(expected)

    async def test_window_resets_after_expiry(self, redis_client):
        """After the window expires, requests are allowed again."""
        test_app = FastAPI()
        test_app.state.redis_client = redis_client

        @test_app.post("/shorten")
        async def shorten():
            return {"ok": True}

        test_app.add_middleware(
            RateLimiterMiddleware,
            fastapi_app=test_app,
            max_requests=3,
            window_seconds=1,  # 1-second window for fast testing
        )

        with TestClient(test_app) as c:
            # Exhaust limit
            for _ in range(3):
                resp = c.post("/shorten", json={"url": "https://x.com"})
                assert resp.status_code == 200
            resp = c.post("/shorten", json={"url": "https://x.com"})
            assert resp.status_code == 429

            # Wait for window to expire
            await asyncio.sleep(1.1)

            # Should be allowed again
            assert c.post("/shorten", json={"url": "https://x.com"}).status_code == 200
