"""Sliding-log rate limiter backed by Redis sorted sets."""

import time

import redis.asyncio as redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding-window rate limiter using Redis sorted sets.

    Tracks request timestamps as scores in a ZSET per IP.
    Defaults: 10 requests per 60-second window on POST /shorten only.

    Expects the wrapped FastAPI app to have ``app.state.redis_client`` set
    (e.g. inside lifespan). Accessed lazily at request time.
    """

    def __init__(
        self,
        app,
        fastapi_app,
        max_requests: int = 10,
        window_seconds: int = 60,
    ):
        super().__init__(app)
        self._fastapi_app = fastapi_app
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    @property
    def redis(self) -> redis.Redis:
        return self._fastapi_app.state.redis_client

    async def dispatch(self, request: Request, call_next):
        if request.method != "POST" or request.url.path != "/shorten":
            return await call_next(request)

        client_ip = request.client.host
        now = time.time()
        window_start = now - self.window_seconds
        key = f"ratelimit:{client_ip}"

        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                # Prune entries outside the sliding window
                pipe.zremrangebyscore(key, 0, window_start)
                # Record current request timestamp
                pipe.zadd(key, {str(now): now})
                # Count remaining entries in window
                pipe.zcard(key)
                # Auto-expire the key slightly after the window closes
                pipe.expire(key, self.window_seconds + 1)
                results = await pipe.execute()
        except Exception:
            # Redis unavailable — skip rate limiting (fail open)
            return await call_next(request)

        count = results[2]
        if count > self.max_requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
            )

        response = await call_next(request)
        # Attach rate-limit headers on successful responses
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, self.max_requests - count)
        )
        return response


