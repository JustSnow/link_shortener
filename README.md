# Link Shortener

Minimal URL shortener built with FastAPI and SQLite. Generates 6-character random keys, stores links in a local `links.db`, and serves a simple frontend for creating shortened URLs.

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

The server starts at `http://localhost:8000`. Open it in a browser to use the web interface.

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

## Tests

The project uses **pytest** with an in-memory SQLite database for isolation.

```bash
# Run all tests
uv run pytest

# With verbose output
uv run pytest -v
```

Tests cover three layers:

- **Service** — key generation, shorten flow, collision retry, URL lookup (mocked repository)
- **Repository** — CRUD operations against in-memory SQLite
- **API** — full endpoint integration via FastAPI's `TestClient`

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
├── app/
│   ├── models.py                    # Pydantic models (Link, ShortenRequest, etc.)
│   ├── dependencies.py              # DI configuration
│   ├── repositories/
│   │   └── link_repository.py       # Async SQLite CRUD operations
│   ├── routers/
│   │   └── links.py                 # API route handlers
│   └── services/
│       └── link_service.py          # Business logic (key gen, shorten, lookup)
└── tests/
    ├── conftest.py                  # Shared fixtures (DB, repo, service, client)
    ├── test_api.py                  # Endpoint integration tests
    ├── test_repository.py           # Repository CRUD tests
    └── test_service.py              # Service unit tests
```

## Tech Stack

- **FastAPI** — web framework and API routing
- **Uvicorn** — ASGI server
- **aiosqlite** — async SQLite driver
- **Pydantic** — request/response validation (`HttpUrl` type)
- **pytest + pytest-asyncio** — testing with async support
