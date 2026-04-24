# Netforge Backend

FastAPI application that powers Netforge.

## Local development (without Docker)

```bash
# from backend/
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Start a local database (docker compose is the easy path; see repo root)
docker compose -f ../docker-compose.dev.yml up -d postgres

# Point DATABASE_URL at localhost instead of the "postgres" container name
export DATABASE_URL="postgresql+asyncpg://netforge:dev@localhost:5432/netforge"
export SESSION_SIGNING_KEY="dev-key-not-for-prod"
export BOOTSTRAP_ADMIN_EMAIL="admin@example.com"

# Apply migrations
alembic upgrade head

# Run the server
uvicorn app.main:app --reload --port 8000
```

Then `curl http://localhost:8000/api/health`.

## Layout

```
app/
├── main.py        # FastAPI app factory, middleware wiring, router registration
├── config.py      # Pydantic BaseSettings loaded from env
├── db.py          # async SQLAlchemy engine, session factory, FastAPI dependency
├── models/        # SQLAlchemy ORM models
├── schemas/       # Pydantic request/response schemas (phase 3+)
├── routers/       # HTTP endpoints grouped by domain
├── services/      # business logic (phase 3+)
└── utils/

alembic/
├── env.py
├── script.py.mako
└── versions/
    ├── 0001_initial.py
    └── 0002_seed.py
```

## Migrations

```bash
# apply everything
alembic upgrade head

# create a new migration (autogenerate against the models)
alembic revision --autogenerate -m "short description"

# step back one revision
alembic downgrade -1
```
