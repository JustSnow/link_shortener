# Архитектура и дизайн Link Shortener

## Обзор

Минимальный сервис сокращения URL на FastAPI + SQLAlchemy (async) + SQLite. Пользователь отправляет длинный URL — получает короткий с 6-символьным ключом. Переход по короткой ссылке делает HTTP 302 редирект на оригинал.

Дополнительно: **rate limiting** через Redis (sliding-window), **Alembic**-миграции, Docker-деплой.

---

## Структура слоёв (Layered Architecture)

Проект разбит на три слоя, каждый из которых зависит только от нижележащего:

```
┌───────────── Router ────────────┐   ← HTTP-запросы/ответы, валидация входных данных
│  /shorten → POST                │
│  /s/{id}    → GET (редирект)    │
│  /         → GET (HTML-страница)│
├───────────── Service ───────────┤   ← Бизнес-логика: генерация ключей, коллизии
│  shorten()                      │
│  get_original_url()             │
├────────── Repository ───────────┤   ← Персистентность (SQLAlchemy ORM + aiosqlite)
│  create(), get_by_id(), exists()│
├───────── SQLAlchemy ORM ────────┤   ← LinkORM → links table
└───────────── SQLite DB ─────────┘
```

Параллельно работает **RateLimiterMiddleware** (Redis) — перехватывает `POST /shorten` до роутера.

### Почему слои, а не всё в роутере?

- **Тестируемость.** Service можно тестировать с моком репозитория без БД. Репозиторий — с реальной in-memory БД без HTTP. Роутеры — через TestClient. Каждый слой изолирован.
- **Подменяемость.** Если завтра нужно PostgreSQL вместо SQLite — меняется только `LinkRepository`. Service и Router не затрагиваются.
- **Читаемость.** В роутере видно *что* происходит (приняли запрос, вернули ответ), а не *как* (SQLAlchemy-запросы, генерация ключей).

---

## config/settings.yml + app/config.py — централизованная конфигурация

Все настройки приложения вынесены в **`config/settings.yml`**:

```yaml
redis:
  url: "redis://localhost:6379/0"

rate_limit:
  max_requests: 10        # запросов на окно
  window_seconds: 60      # размер окна в секундах
  method: "POST"          # HTTP-метод для ограничения
  path: "/shorten"        # путь для защиты
```

Модуль **`app/config.py`** загружает YAML и валидирует через Pydantic:

```python
class RedisSettings(BaseModel):
    url: str = "redis://localhost:6379/0"

class RateLimitSettings(BaseModel):
    max_requests: int = 10
    window_seconds: int = 60
    method: str = "POST"
    path: str = "/shorten"

class Settings(BaseModel):
    redis: RedisSettings = RedisSettings()
    rate_limit: RateLimitSettings = RateLimitSettings()
```

### Преимущества перед хардкодом

- **Одно место правки.** Изменить лимит или URL Redis — один файл, без поиска по коду.
- **Валидация типов.** Pydantic проверяет значения при загрузке — опечатка в `max_requests: "десять"` упадёт на старте, а не в рантайме.
- **Дефолты из модели.** Если файл отсутствует или поле пропущено — используется значение по умолчанию из Pydantic. Приложение всегда стартует.
- **Переменные окружения.** Каждое поле можно переопределить через env с префиксом `LINK_` (например, `LINK_REDIS_URL`).

### Почему YAML, а не `.env`?

YAML поддерживает вложенные структуры (`redis.url`, `rate_limit.max_requests`) — `.env` плоский и не группирует настройки. Для одного-двух параметров `.env` подходит; для нескольких секций YAML чище.

---

## main.py — точка входа и lifespan

```python
from app.config import settings

@asynccontextmanager
async def lifespan(application: FastAPI):
    engine = create_engine()
    session_factory = create_session_factory(engine)

    _run_migrations()  # Alembic upgrade head

    repo = LinkRepository(session_factory())
    configure_deps(LinkService(repo))

    application.state.redis_client = aioredis.from_url(
        settings.redis.url, decode_responses=True
    )

    yield

    await repo.session.close()
    await engine.dispose()
    await application.state.redis_client.aclose()


app = FastAPI(lifespan=lifespan)
rl = settings.rate_limit
app.add_middleware(
    RateLimiterMiddleware,
    fastapi_app=app,
    max_requests=rl.max_requests,
    window_seconds=rl.window_seconds,
    method=rl.method,
    path=rl.path,
)
app.include_router(links_router)
```

### Что делает `lifespan` по шагам

1. **Создаёт SQLAlchemy engine** — async-движок поверх aiosqlite (`sqlite+aiosqlite:///links.db`).
2. **Запускает Alembic-миграции** — `_run_migrations()` вызывает `alembic upgrade head`, применяя все pending-ревижии. Схема БД всегда актуальна при старте.
3. **Создаёт session factory + repository** — `async_sessionmaker` привязан к engine, репозиторий получает один session.
4. **Конфигурирует DI** — глобальный синглтон `LinkService(repo)` устанавливается через `configure_deps()`.
5. **Подключается к Redis** — URL берётся из `settings.redis.url` (config/settings.yml). Клиент сохраняется в `app.state.redis_client` для middleware.
6. **При остановке** — закрывает session, engine (connection pool), и Redis-клиент.

### Почему `lifespan`, а не `startup`/`shutdown`?

FastAPI deprecated отдельные события `on_event`. `lifespan` — это единый async context manager, который:

1. Инициализирует всё **до** первого запроса.
2. Закрывает все ресурсы автоматически при остановке (благодаря `async with`).

### Почему Alembic вызывается из lifespan?

Миграции применяются один раз при старте — разработчику не нужно помнить про ручной `alembic upgrade head`. В тестах lifespan заменяется на no-op, и миграции пропускаются.

---

## app/db/ — слой базы данных

### app/db/__init__.py — engine + session factory

```python
def create_engine(db_url: str | None = None) -> object:
    url = db_url or "sqlite+aiosqlite:///links.db"
    return create_async_engine(url, echo=False)


def create_session_factory(engine: object) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

`expire_on_commit=False` — объекты ORM не инвалидируются после commit. Это важно для async-сессий: без этого доступ к атрибутам после commit потребовал бы ещё одного запроса к БД.

### app/db/models.py — SQLAlchemy ORM модели

```python
class Base(DeclarativeBase):
    pass


class LinkORM(Base):
    __tablename__ = "links"

    id = Column(String(6), primary_key=True)
    original_url = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
```

### Почему SQLAlchemy ORM, а не raw SQL?

- **Alembic autogenerate** — миграции генерируются автоматически из моделей (`alembic revision --autogenerate`). С raw SQL это невозможно.
- **Type safety** — `select(LinkORM).where(...)` вместо строковых запросов.
- **Портативность** — смена БД (PostgreSQL) требует минимальных изменений.

### Почему две модели — Pydantic и ORM?

| Модель | Где | Зачем |
|--------|-----|-------|
| `Link` (Pydantic) | `app/models.py` | Валидация API, сериализация ответов, доменная сущность |
| `LinkORM` (SQLAlchemy) | `app/db/models.py` | Схема БД, миграции Alembic, SQL-запросы |

Repository конвертирует ORM → Pydantic через `_to_domain()`. Это чёткое разделение: API не зависит от ORM, а ORM — от формата запросов.

---

## app/models.py — Pydantic-модели

```python
class Link(BaseModel):
    id: str
    original_url: str
    created_at: datetime | None = None


class ShortenRequest(BaseModel):
    url: HttpUrl  # ← валидирует формат URL автоматически


class ShortenResponse(BaseModel):
    short_url: str
```

### Почему `HttpUrl`, а не `str`?

Pydantic тип `HttpUrl`:

- Проверяет, что URL начинается с `http://` или `https://`.
- Нормализует URL (добавляет trailing slash, если нет пути).
- Возвращает 422 автоматически при валидации — не нужно писать ручные проверки.

---

## app/dependencies.py — Dependency Injection

```python
_link_service: LinkService | None = None


def configure(service: LinkService) -> None:
    global _link_service
    _link_service = service


def get_link_service() -> LinkService:
    if _link_service is None:
        raise RuntimeError("Application not started")
    return _link_service
```

### Почему глобальная переменная, а не контейнер DI?

Проект минимальный. Тяжёлые фреймворки (Dependency Injector, Inject) избыточны для одного сервиса. Глобальный синглтон:

- Устанавливается один раз в `lifespan` при старте.
- Подменяется в тестах через `configure_deps(test_service)`.
- Не создаёт circular imports — модуль не импортирует Service напрямую, только тип для аннотации.

---

## app/services/link_service.py — бизнес-логика

```python
CHARS = string.ascii_letters + string.digits  # a-zA-Z0-9 (62 символа)
KEY_LEN = 6  # 62^6 ≈ 56 млрд комбинаций


class LinkService:
    def __init__(self, repository: LinkRepository):
        self.repository = repository

    @staticmethod
    def _generate_key() -> str:
        return "".join(random.choices(CHARS, k=KEY_LEN))

    async def shorten(self, request: ShortenRequest) -> ShortenResponse:
        key = self._generate_key()
        while await self.repository.exists(key):  # ← защита от коллизий
            key = self._generate_key()

        link = Link(id=key, original_url=str(request.url))
        await self.repository.create(link)
        return ShortenResponse(short_url=f"http://localhost:8000/s/{key}")

    async def get_original_url(self, short_id: str) -> str | None:
        link = await self.repository.get_by_id(short_id)
        if link is None:
            return None
        return link.original_url
```

### Почему 6 символов из 62?

- **62^6 ≈ 56 миллиардов** уникальных ключей — достаточно для любого реалистичного использования.
- Коротко и читаемо (6 символов помещаются в SMS, QR-код компактный).
- Буквы + цифры — URL-safe без специальных символов.

### Почему `while exists()` вместо UNIQUE constraint?

Оба подхода работают. Здесь выбран программный подход:

1. **Простота.** Не нужно обрабатывать `IntegrityError` от SQLAlchemy.
2. **Предсказуемость.** Коллизия при 6 символах из 62 практически невозможна (birthday paradox требует ~300 млн записей для 50% шанса). Цикл почти никогда не повторится даже один раз.

---

## app/repositories/link_repository.py — персистентность

```python
class LinkRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, link: Link) -> Link:
        orm = LinkORM(id=link.id, original_url=link.original_url)
        self.session.add(orm)
        await self.session.commit()
        return link

    async def get_by_id(self, short_id: str) -> Link | None:
        row = await self.session.execute(select(LinkORM).where(LinkORM.id == short_id))
        result = row.scalar_one_or_none()
        if result is None:
            return None
        return self._to_domain(result)

    async def exists(self, short_id: str) -> bool:
        stmt = select(LinkORM.id).where(LinkORM.id == short_id)
        row = await self.session.execute(stmt)
        return row.scalar() is not None
```

### Почему `select(…).scalar_one_or_none()`?

SQLAlchemy 2.0 стиль. `scalar_one_or_none()` возвращает одну запись или `None` — идеально для поиска по primary key. Аналог `fetchone()` из raw SQL, но типизированный.

### Почему `exists` использует `select(LinkORM.id)` вместо `select(func.count())`?

`select(LinkORM.id).where(...)` генерирует `SELECT id FROM links WHERE id = ? LIMIT 1`. SQLAlchemy сам оптимизирует: если найдена хотя бы одна строка — `scalar()` вернёт значение, иначе `None`. Не нужно сканировать все совпадения.

### Конвертация ORM → Domain

```python
@staticmethod
def _to_domain(row: LinkORM) -> Link:
    return Link(id=row.id, original_url=row.original_url, created_at=row.created_at)
```

Репозиторий — мост между слоями. Он принимает Pydantic-модели на вход и возвращает их на выход, а внутри конвертирует в/из ORM.

---

## app/routers/links.py — HTTP-роутеры

```python
@router.post("/shorten", response_model=ShortenResponse)
async def shorten(
    body: ShortenRequest, service: LinkService = Depends(get_link_service)
):
    return await service.shorten(body)


@router.get("/s/{short_id}")
async def redirect(short_id: str, service: LinkService = Depends(get_link_service)):
    original_url = await service.get_original_url(short_id)
    if original_url is None:
        raise HTTPException(status_code=404, detail="Link not found")
    return RedirectResponse(url=original_url, status_code=302)


@router.get("/")
async def index():
    with open("static/index.html") as f:
        return HTMLResponse(content=f.read())
```

### Почему роутеры тонкие?

Роутер — это «дверь» между HTTP и бизнес-логикой. Его задача:

1. Принять запрос (FastAPI сам парсит JSON → Pydantic модель).
2. Передать в сервис.
3. Вернуть ответ или ошибку.

Вся логика — в Service. Это делает роутеры тривиальными и легко тестируемыми.

### Почему 302, а не 301?

- **301 (Moved Permanently)** — браузеры кэшируют редирект навсегда. Если ссылка удалится или изменится — пользователь застрянет на старом URL.
- **302 (Found)** — временный редирект, не кэшируется. Каждый переход проверяется в БД.

---

## app/middleware.py — Rate Limiter

```python
class RateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, fastapi_app, max_requests=10, window_seconds=60):
        ...

    async def dispatch(self, request: Request, call_next):
        if request.method != "POST" or request.url.path != "/shorten":
            return await call_next(request)  # ← пропускаем другие эндпоинты

        client_ip = request.client.host
        key = f"ratelimit:{client_ip}"

        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(key, 0, window_start)  # удалить старые
            pipe.zadd(key, {str(now): now})               # добавить текущий
            pipe.zcard(key)                                # посчитать
            pipe.expire(key, self.window_seconds + 1)      # авто-удаление
            results = await pipe.execute()

        if count > max_requests:
            return JSONResponse(status_code=429, ...)
```

### Как работает sliding-window на Redis sorted sets

1. **ZSET** (`ratelimit:<ip>`) хранит timestamp как member и score одновременно.
2. При каждом запросе старые записи (вне окна) удаляются через `zremrangebyscore`.
3. Текущий timestamp добавляется через `zadd`.
4. `zcard` считает количество записей в окне — это текущее число запросов.
5. Ключ автоматически истекает через `expire`, освобождая память Redis.

### Почему pipeline?

Четыре операции (`zremrangebyscore`, `zadd`, `zcard`, `expire`) выполняются атомарно за один round-trip к Redis. Без pipeline это было бы 4 отдельных запроса — медленнее и неатомарно (другой запрос мог бы проскользнуть между операциями).

### Параметры из конфига

Все параметры middleware читаются из `settings.rate_limit`:

| Параметр | Поле в YAML | Дефолт |
|----------|-------------|--------|
| Лимит запросов | `rate_limit.max_requests` | `10` |
| Размер окна | `rate_limit.window_seconds` | `60` |
| HTTP-метод | `rate_limit.method` | `POST` |
| Путь | `rate_limit.path` | `/shorten` |

Изменить лимит — править `config/settings.yml`, не код.

### Fail-open поведение

Если Redis недоступен, middleware **пропускает запрос** без ограничения:

```python
except Exception:
    return await call_next(request)  # Redis down → skip rate limiting
```

Это предотвращает блокировку легитимного трафика при падении кэша. Цена — временное отсутствие защиты от спама.

### Заголовки ответа

Успешные ответы включают метаданные:

```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
```

---

## static/index.html — фронтенд

Простая одностраничная форма на чистом HTML/CSS/JS (без фреймворков):

- **Форма** с `<input type="url">` — браузер сам валидирует формат URL до отправки.
- **fetch API** для POST `/shorten` без перезагрузки страницы.
- **Обработка ошибок** — показывает 422 как «Некорректный URL», остальные ошибки со статусом.

### Почему нет React/Vue?

Одна форма с одним input — максимум, что можно уместить в 50 строк чистого JS. Фреймворк добавил бы npm + сборщик + мегабайты зависимостей. Для одной формы — overkill.

---

## Тесты

Четыре уровня тестирования:

### test_service.py — unit-тесты (моки)

Репозиторий заменён на `AsyncMock`. Проверяется только бизнес-логика:

- Генерация ключа правильной длины и из правильного алфавита.
- Создание ссылки через репозиторий.
- Повторная генерация при коллизии (3 попытки).
- Возврат URL или None при поиске.

### test_repository.py — интеграционные тесты (in-memory SQLite)

Реальная БД в памяти (`:memory:`) через SQLAlchemy async engine. Проверяется, что ORM-запросы работают корректно:

- Запись и чтение записи.
- `None` для несуществующего ID.
- `exists()` возвращает True/False правильно.

### test_api.py — end-to-end тесты (TestClient)

Полный HTTP-стек через FastAPI TestClient:

- POST `/shorten` → 200 с короткой ссылкой.
- POST `/shorten` с невалидным URL → 422.
- GET `/s/{id}` → 302 редирект на оригинал.
- GET `/s/ZZZZZZ` (не существует) → 404.
- GET `/` → HTML-страница.

### test_rate_limiter.py — тесты rate limiter

Реальный Redis (авто-skip если Redis не запущен):

- Пропускает до лимита запросов.
- Возвращает 429 при превышении.
- Не ограничивает другие эндпоинты.
- Заголовки `X-RateLimit-*` присутствуют и корректны.
- Счётчик уменьшается с каждым запросом.
- Окно сбрасывается после истечения (1 сек в тестах).

### conftest.py — общие фикстуры

```python
@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def app_client(repository, monkeypatch):
    # Заменяет production lifespan на no-op (без Redis + Alembic).
    monkeypatch.setattr(main.app.router, "lifespan_context", _test_lifespan)
    ...
```

### Почему pytest-asyncio с `asyncio_mode = "auto"`?

Все тесты асинхронные (`async def`). Режим `auto` автоматически запускает их в event loop без явного `@pytest.mark.asyncio` на каждом тесте.

---

## Alembic — миграции БД

### alembic/env.py — синхронный runner

```python
def run_migrations_online() -> None:
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection, target_metadata=target_metadata)
        ...
```

### Почему синхронный engine для миграций?

SQLite DDL — синхронная операция. Вызов `asyncio.run()` изнутри уже работающего event loop (lifespan) вызывает ошибку. Синхронный engine с `NullPool` решает проблему: миграции выполняются в том же потоке, без конфликтов с async-циклом.

### Автогенерация миграций

```bash
uv run alembic revision --autogenerate -m "description"
```

Alembic сравнивает текущую схему БД с `Base.metadata` из `app/db/models.py` и генерирует diff.

---

## Docker-стек

### docker-compose.yml — два сервиса

| Сервис | Образ | Порт | Зачем |
|--------|-------|------|-------|
| `app` | Multi-stage build (Python 3.12-slim) | 8000 | FastAPI приложение |
| `redis` | `redis:7-alpine` | 6379 | Rate limiter backend |

### Dockerfile — multi-stage сборка

```dockerfile
# Stage 1: builder — устанавливает зависимости через uv
FROM python:3.12-slim AS builder
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev   # только production-зависимости

# Stage 2: runtime — копирует .venv + исходники
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Multi-stage сборка уменьшает размер образа: dev-зависимости (pytest, ruff) не попадают в финальный образ.

### Почему uv вместо pip?

`uv` от Astral — drop-in замена pip/venv, работающая на Rust. В 10–100 раз быстрее установки зависимостей. `uv sync --frozen` гарантирует детерминированную сборку из lock-файла.

---

## Почему SQLite + aiosqlite?

- **Нулевая настройка.** Файл `links.db` создаётся автоматически через Alembic. Нет Docker для БД, нет отдельного процесса.
- **Один файл = простой бэкап и деплой.**
- **SQLAlchemy async** — полноценный ORM с connection pooling поверх aiosqlite.

Для высокой нагрузки (тысячи запросов в секунду) SQLite не подходит — нужно PostgreSQL + пул соединений. Но для минимального сервиса это правильный выбор.

---

## Что можно улучшить (не сделано намеренно)

| Улучшение | Почему пока не нужно |
|-----------|---------------------|
| UNIQUE constraint на `id` | Коллизии практически невозможны при 62^6 комбинациях |
| TTL / истечение ссылок | Сервис минимальный, без требований к удалению |
| Аналитика (счётчик кликов) | Не было в требованиях |
| Аутентификация | Нет пользователей — ограничивать некого |
| HTTPS в ответе (`localhost:8000`) | Hardcoded URL — в продакшене берётся из `request.base_url` |
