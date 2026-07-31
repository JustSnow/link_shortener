# Link Shortener

Minimal URL shortener built with FastAPI, SQLAlchemy, and SQLite. Generates 6-character random keys, stores links in a local `links.db` (managed by Alembic migrations), and serves a simple frontend for creating shortened URLs.

## Requirements

- Python >= 3.12
- [uv](https://github.com/astral-sh/uv) (for dependency management)

## Quick Start

```bash
# Install dependencies
uv sync

# Run the server (with auto-reload)
uv run uvicorn main:app --reload

# Or without reload for production
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

The server starts at `http://localhost:8000`. On first run, Alembic automatically creates the database schema (`links.db`). Open it in a browser to use the web interface.

## Docker

Run the app with Redis (required for rate limiting) via **docker-compose**:

```bash
# Start app + Redis
sudo docker compose up --build

# Detached mode
sudo docker compose up -d --build

# Stop and remove containers
sudo docker compose down
```

The stack includes two services:

| Service | Image | Port |
|---------|-------|------|
| `app`   | Built from `Dockerfile` (multi-stage, Python 3.12-slim) | `8000` |
| `redis` | `redis:7-alpine` | `6379` |

SQLite data is persisted via a bind mount (`./links.db`), Redis data via a named volume.

### Running without docker-compose

```bash
# Build the image
sudo docker build -t link-shortener .

# Run with a local Redis (must be running on port 6379)
sudo docker run -p 8000:8000 \
  -v $(pwd)/links.db:/app/links.db \
  --network host \
  link-shortener
```

## Rate Limiter

The `/shorten` endpoint is protected by a **sliding-window rate limiter** backed by Redis sorted sets.

### How it works

1. Each request is identified by the client IP address.
2. A Redis sorted set (`ratelimit:<ip>`) stores request timestamps as both members and scores.
3. On each `POST /shorten`, entries older than the window are pruned, then the current timestamp is added.
4. If the count exceeds the limit, a **`429 Too Many Requests`** response is returned.

### Defaults

| Parameter | Value |
|-----------|-------|
| Max requests | `10` |
| Window size  | `60 seconds` |
| Scope        | `POST /shorten` only (other endpoints are unrestricted) |

### Response headers

Successful responses include rate-limit metadata:

```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
```

### Configuration

Change limits by editing the `RateLimiterMiddleware` init in `main.py`:

```python
app.add_middleware(
    RateLimiterMiddleware,
    fastapi_app=app,
    max_requests=20,   # requests allowed per window
    window_seconds=60,  # sliding window size
)
```

### Fail-open behavior

If Redis is unreachable the middleware **skips rate limiting** and lets the request through. This avoids blocking legitimate traffic when the cache layer is down.

## Database & Migrations

The schema is defined as SQLAlchemy ORM models in `app/db/models.py` and managed by **Alembic**. On every startup, pending migrations are applied automatically — no manual step needed.

### Generating a new migration

After changing `app/db/models.py`, generate a revision:

```bash
# Auto-detect schema changes
uv run alembic revision --autogenerate -m "add new column"

# Or create an empty revision for manual SQL
uv run alembic revision -m "custom migration"
```

### Running migrations manually

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Rollback one step
uv run alembic downgrade -1

# Check current version
uv run alembic current

# View migration history
uv run alembic history
```

### How it works

1. `main.py` lifespan calls `alembic upgrade head` on startup.
2. Alembic reads the ORM models from `app/db/models.py` via `Base.metadata`.
3. The `links.db` file is created/updated automatically — no manual schema management.
4. Tests use an in-memory SQLite engine with tables created via `Base.metadata.create_all`, bypassing Alembic for speed.

## API

### Shorten a URL

```bash
curl -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/some-long-page"}'
```

**Response:**

```json
{"short_url": "/s/aB3xYz"}
```

The `short_url` is returned as a relative path. Prepend your server address to get the full URL (e.g., `http://localhost:8000/s/aB3xYz`).

### Redirect to original URL

Visit the short URL in a browser or via curl:

```bash
curl -I http://localhost:8000/s/aB3xYz
# HTTP/1.1 302 Found → Location: https://example.com/some-long-page
```

### Error responses

| Status | Condition |
|--------|-----------|
| `422`  | Invalid or missing URL in request body |
| `404`  | Short link not found |
| `429`  | Rate limit exceeded (see [Rate Limiter](#rate-limiter)) |

## Tests

The project uses **pytest** with an in-memory SQLite database for isolation.

```bash
# Run all tests
uv run pytest

# With verbose output
uv run pytest -v
```

Tests cover four layers:

- **Service** — key generation, shorten flow, collision retry, URL lookup (mocked repository)
- **Repository** — CRUD operations against in-memory SQLite
- **API** — full endpoint integration via FastAPI's `TestClient`
- **Rate limiter** — sliding-window logic with real Redis (auto-skipped if Redis is down)

## Linting, Formatting & Coverage

The project uses **ruff** for linting/formatting and **pytest-cov** for coverage.

```bash
# Check for issues (lint + format)
uv run ruff check .
uv run ruff format --check .

# Auto-fix fixable issues & reformat
uv run ruff check --fix .
uv run ruff format .

# Run tests with coverage report (fail_under = 80%)
uv run pytest --cov

# HTML coverage report (opens in browser)
uv run pytest --cov --cov-report=html && xdg-open htmlcov/index.html
```

## Project Structure

```
link_shortener/
├── main.py                          # FastAPI app entry point & lifespan
├── pyproject.toml                   # Dependencies and project metadata
├── static/
│   └── index.html                   # Frontend page
├── alembic.ini                      # Alembic configuration
├── alembic/
│   ├── env.py                       # Async-safe migration runner
│   └── versions/                    # Migration scripts (auto-generated)
├── app/
│   ├── models.py                    # Pydantic models (Link, ShortenRequest, etc.)
│   ├── db/
│   │   ├── __init__.py              # Engine + session factory
│   │   └── models.py                # SQLAlchemy ORM models (single source of truth)
│   ├── dependencies.py              # DI configuration
│   ├── middleware.py                # RateLimiterMiddleware (Redis-backed)
│   ├── repositories/
│   │   └── link_repository.py       # Async SQLite CRUD operations
│   ├── routers/
│   │   └── links.py                 # API route handlers
│   └── services/
│       └── link_service.py          # Business logic (key gen, shorten, lookup)
├── docker-compose.yml               # App + Redis stack
├── Dockerfile                       # Multi-stage build (Python 3.12-slim)
└── tests/
    ├── conftest.py                  # Shared fixtures (DB, repo, service, client)
    ├── test_api.py                  # Endpoint integration tests
    ├── test_rate_limiter.py         # Rate limiter unit & integration tests
    ├── test_repository.py           # Repository CRUD tests
    └── test_service.py              # Service unit tests
```

## Tech Stack

- **FastAPI** — web framework and API routing
- **Uvicorn** — ASGI server
- **SQLAlchemy 2.0 (async)** — ORM + connection pooling over aiosqlite
- **Alembic** — database migrations (auto-applied on startup)
- **Redis 7** — sliding-window rate limiter backend (redis.asyncio)
- **Pydantic** — request/response validation (`HttpUrl` type)
- **pytest + pytest-asyncio** — testing with async support
