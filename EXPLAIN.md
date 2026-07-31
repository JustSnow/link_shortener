# Архитектура и дизайн Link Shortener

## Обзор

Минимальный сервис сокращения URL на FastAPI + SQLite. Пользователь отправляет длинный URL — получает короткий с 6-символьным ключом. Переход по короткой ссылке делает HTTP 302 редирект на оригинал.

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
├────────── Repository ───────────┤   ← Персистентность (SQLite)
│  create(), get_by_id(), exists()│
└───────────── SQLite DB ─────────┘
```

### Почему слои, а не всё в роутере?

- **Тестируемость.** Service можно тестировать с моком репозитория без БД. Репозиторий — с реальной in-memory БД без HTTP. Роутеры — через TestClient. Каждый слой изолирован.
- **Подменяемость.** Если завтра нужно PostgreSQL вместо SQLite — меняется только `LinkRepository`. Service и Router не затрагиваются.
- **Читаемость.** В роутере видно *что* происходит (приняли запрос, вернули ответ), а не *как* (SQL-запросы, генерация ключей).

---

## main.py — точка входа и lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS links ...")
        await db.commit()

        repo = LinkRepository(db)
        configure_deps(LinkService(repo))

        yield
```

### Почему `lifespan`, а не `startup`/`shutdown`?

FastAPI deprecated отдельные события `on_event`. `lifespan` — это единый async context manager, который:

1. Открывает БД и создаёт таблицу **до** первого запроса.
2. Конфигурирует DI (зависимости) один раз при старте.
3. Закрывает соединение с БД автоматически при остановке сервера (благодаря `async with`).

### Почему таблица создаётся здесь, а не в репозитории?

Создание схемы — это инициализация приложения, а не часть бизнес-логики хранения. Репозиторий знает *как* читать/писать данные, но не обязан знать *что* делать при старте сервера. Разделение ответственности (Single Responsibility Principle).

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

### Почему `Link` — это модель, а не dataclass?

Pydantic BaseModel даёт:

- Автоматическую сериализацию (нужна для тестов и потенциального JSON).
- Валидацию типов.
- Единую нотацию со всеми остальными моделями в проекте.

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

### Почему нет `yield Depends(...)`?

FastAPI поддерживает factory-функции с yield:

```python
@router.post("/shorten")
async def shorten(body: ShortenRequest, service=Depends(get_link_service)): ...
```

Но наш сервис — синглтон без состояния между запросами. Нет смысла создавать его на каждый запрос. Глобальная переменная + `Depends()` — это просто способ передать уже созданный экземпляр в роутер.

---

## app/services/link_service.py — бизнес-логика

```python
CHARS = string.ascii_letters + string.digits  # a-zA-Z0-9 (62 символа)
KEY_LEN = 6  # 62^6 ≈ 56 млрд комбинаций


class LinkService:
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
```

### Почему 6 символов из 62?

- **62^6 ≈ 56 миллиардов** уникальных ключей — достаточно для любого реалистичного использования.
- Коротко и читаемо (6 символов помещаются в SMS, QR-код компактный).
- Буквы + цифры — URL-safe без специальных символов.

### Почему `while exists()` вместо UNIQUE constraint?

Оба подхода работают. Здесь выбран программный подход:

1. **Простота.** Не нужно обрабатывать `IntegrityError` от SQLite.
2. **Предсказуемость.** Коллизия при 6 символах из 62 практически невозможна (birthday paradox требует ~300 млн записей для 50% шанса). Цикл почти никогда не повторится даже один раз.

Альтернатива — UNIQUE constraint на уровне БД + обработка исключения. Это надёжнее при высокой нагрузке, но сложнее в коде и тестах. Для минимального сервиса текущий подход достаточен.

### Почему `_generate_key` — staticmethod?

Метод не использует `self`. Он чистая функция: вход (ничего) → выход (случайная строка). Staticmethod сигнализирует, что состояние объекта не нужно.

---

## app/repositories/link_repository.py — персистентность

```python
class LinkRepository:
    async def create(self, link: Link) -> Link:
        await self.db.execute(
            "INSERT INTO links (id, original_url) VALUES (?, ?)",
            (link.id, link.original_url),
        )
        await self.db.commit()
        return link

    async def get_by_id(self, short_id: str) -> Link | None:
        async with self.db.execute(
            "SELECT id, original_url, created_at FROM links WHERE id = ?",
            (short_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return Link(id=row[0], original_url=row[1], created_at=row[2])

    async def exists(self, short_id: str) -> bool:
        async with self.db.execute(
            "SELECT 1 FROM links WHERE id = ?", (short_id,)
        ) as cursor:
            return await cursor.fetchone() is not None
```

### Почему параметризованные запросы (`?`), а не f-strings?

SQL-инъекция. Параметризация — единственный безопасный способ подставлять пользовательские данные в SQL.

### Почему `SELECT 1`, а не `SELECT COUNT(*)` для `exists()`?

`SELECT 1` останавливается на первой найденной строке и возвращает `None` если нет строк. `COUNT(*)` сканирует все совпадения (хотя с PRIMARY KEY это одно и то же, но `SELECT 1` — более явный сигнал «мне нужно только наличие»).

### Почему `async with self.db.execute()` вместо простого `await`?

aiosqlite возвращает контекстный менеджер для курсора. Это гарантирует корректное освобождение ресурсов даже при исключениях.

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
- **302 (Found)** — временный редирект, не кэшируется. Каждый переход проверяется в БД. Это правильнее для сокращателя ссылок.

### Почему `index()` читает файл каждый раз?

Для минимального проекта это нормально — один файл, читаемый за миллисекунды. В продакшене можно было бы:

- Кэшировать содержимое в памяти при старте.
- Использовать `StaticFiles` middleware от FastAPI.

Но это добавляет код без реальной пользы для текущего масштаба.

---

## static/index.html — фронтенд

Простая одностраничная форма на чистом HTML/CSS/JS (без фреймворков):

- **Форма** с `<input type="url">` — браузер сам валидирует формат URL до отправки.
- **fetch API** для POST `/shorten` без перезагрузки страницы.
- **Обработка ошибок** — показывает 422 как «Некорректный URL», остальные ошибки со статусом.

### Почему нет React/Vue?

Одна форма с одним input — это максимум, что можно уместить в 50 строк чистого JS. Фреймворк добавил бы:

- npm + сборщик (Vite/Webpack).
- Десятки мегабайт зависимостей.
- Сложность деплоя.

Для одной формы — overkill.

---

## Тесты

Три уровня тестирования, каждый с своей стратегией:

### test_service.py — unit-тесты (моки)

Репозиторий заменён на `AsyncMock`. Проверяется только бизнес-логика:

- Генерация ключа правильной длины и из правильного алфавита.
- Создание ссылки через репозиторий.
- Повторная генерация при коллизии (3 попытки).
- Возврат URL или None при поиске.

### test_repository.py — интеграционные тесты (in-memory SQLite)

Реальная БД в памяти (`:memory:`). Проверяется, что SQL работает корректно:

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

### Почему pytest-asyncio с `asyncio_mode = "auto"`?

Все тесты асинхронные (`async def`). Режим `auto` автоматически запускает их в event loop без явного `@pytest.mark.asyncio` на каждом тесте (хотя маркеры оставлены для совместимости).

---

## Почему SQLite, а не PostgreSQL?

- **Нулевая настройка.** Файл `links.db` создаётся автоматически. Нет Docker, нет отдельного процесса БД.
- **Один файл = простой бэкап и деплой.**
- **aiosqlite** — полноценный async драйвер, API совместим с sqlite3.

Для высокой нагрузки (тысячи запросов в секунду) SQLite не подходит — нужно PostgreSQL + пул соединений. Но для минимального сервиса это правильный выбор.

---

## Что можно улучшить (не сделано намеренно)

| Улучшение | Почему пока не нужно |
|-----------|---------------------|
| UNIQUE constraint на `id` | Коллизии практически невозможны при 62^6 комбинациях |
| TTL / истечение ссылок | Сервис минимальный, без требований к удалению |
| Аналитика (счётчик кликов) | Не было в требованиях |
| Rate limiting | Нет аутентификации — ограничивать некого |
| HTTPS в ответе (`localhost:8000`) | Hardcoded URL — в продакшене берётся из `request.base_url` |
