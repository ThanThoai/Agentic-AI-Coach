# FastAPI Backend Rules

## Project Structure

```
backend/app/
├── api/
│   └── v1/
│       ├── router.py          # aggregates all v1 routers
│       ├── auth.py
│       ├── workouts.py
│       ├── coaching.py
│       └── users.py
├── core/
│   ├── config.py              # Settings via pydantic-settings
│   ├── security.py            # JWT, password hashing
│   ├── logging.py             # Structured logger setup
│   └── dependencies.py        # Shared FastAPI Depends
├── models/                    # SQLAlchemy ORM models (one file per domain)
├── schemas/                   # Pydantic v2 schemas (request + response)
├── services/                  # Business logic (no DB calls here)
├── repositories/              # All DB access lives here
├── agents/                    # Claude AI agent logic
└── main.py
```

## Patterns

### Application Setup (main.py)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.logging import setup_logging
from app.api.v1.router import router as v1_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    yield

app = FastAPI(title="Coach Agent API", version="1.0.0", lifespan=lifespan)
app.include_router(v1_router, prefix="/api/v1")
```

### Configuration

Use `pydantic-settings` with `.env` file. Never hardcode secrets.

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    redis_url: str
    anthropic_api_key: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    class Config:
        env_file = ".env"

settings = Settings()
```

### Route Handlers

- Thin handlers — delegate all logic to service layer
- Always type return values with response models
- Use `status_code` explicitly

```python
@router.post("/workouts", response_model=WorkoutResponse, status_code=201)
async def create_workout(
    payload: WorkoutCreate,
    current_user: User = Depends(get_current_user),
    service: WorkoutService = Depends(get_workout_service),
) -> WorkoutResponse:
    return await service.create(user_id=current_user.id, payload=payload)
```

### Service Layer

- Services receive repository + other service dependencies via constructor
- All business logic here, no SQLAlchemy queries
- Raise `HTTPException` only at the API layer — services raise domain exceptions

```python
class WorkoutService:
    def __init__(self, repo: WorkoutRepository, coach: CoachingAgent):
        self._repo = repo
        self._coach = coach

    async def create(self, user_id: UUID, payload: WorkoutCreate) -> WorkoutResponse:
        # normalize units to kg before storage
        normalized = payload.normalize_units()
        workout = await self._repo.create(user_id=user_id, data=normalized)
        return WorkoutResponse.model_validate(workout)
```

### Repository Layer

- One repository class per SQLAlchemy model
- All queries use async SQLAlchemy sessions
- Never return ORM objects past the repository boundary — return domain models or dicts

```python
class WorkoutRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_user(self, user_id: UUID, limit: int = 50) -> list[WorkoutRow]:
        result = await self._session.execute(
            select(WorkoutModel)
            .where(WorkoutModel.user_id == user_id)
            .order_by(WorkoutModel.date.desc())
            .limit(limit)
        )
        return result.scalars().all()
```

### Dependency Injection

Wire services and repos in `core/dependencies.py`:

```python
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session

def get_workout_repository(session: AsyncSession = Depends(get_db_session)):
    return WorkoutRepository(session)

def get_workout_service(repo: WorkoutRepository = Depends(get_workout_repository)):
    return WorkoutService(repo)
```

### Error Handling

Add a global exception handler — never let raw exceptions reach the client:

```python
@app.exception_handler(DomainException)
async def domain_exception_handler(request: Request, exc: DomainException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})
```

### Background Tasks

Use FastAPI `BackgroundTasks` for non-blocking work (e.g., post-workout AI analysis):

```python
@router.post("/workouts/{id}/analyze")
async def trigger_analysis(
    id: UUID,
    background_tasks: BackgroundTasks,
    service: WorkoutService = Depends(get_workout_service),
):
    background_tasks.add_task(service.analyze_workout, workout_id=id)
    return {"status": "analysis_queued"}
```

## Dependency Management (uv)

Use `uv` for all Python env and package operations — never `pip` directly.

```bash
# Sync all deps from uv.lock
uv sync

# Add runtime dep
uv add httpx

# Add dev-only dep
uv add --dev pytest pytest-asyncio httpx

# Run any command inside the managed venv
uv run uvicorn app.main:app --reload
uv run pytest
uv run alembic upgrade head
```

Keep `uv.lock` committed — it is the source of truth for reproducible builds.

`pyproject.toml` structure:
```toml
[project]
name = "coach-agent-backend"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg",
    "pydantic-settings>=2.0",
    "structlog",
    "anthropic",
]

[dependency-groups]
dev = [
    "pytest",
    "pytest-asyncio",
    "httpx",
]
```

## Testing

- Use `pytest` + `httpx.AsyncClient` for integration tests
- Use a real test database (never mock SQLAlchemy)
- Factory fixtures in `conftest.py`
- Run via `uv run pytest`

```python
@pytest.fixture
async def client(db_session):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
```

## Don'ts

- No logic in route handlers beyond input validation and calling the service
- No raw SQL strings — always use SQLAlchemy ORM or `text()` with bound params
- No `print()` — use structured logger
- No global mutable state outside the `lifespan` context manager
