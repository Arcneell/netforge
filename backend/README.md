# Netforge Backend

API FastAPI pour Netforge.

## Développement local (sans Docker)

```bash
# depuis backend/
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# démarrer une DB locale (docker compose recommandé, cf racine repo)
docker compose -f ../docker-compose.dev.yml up -d postgres

# exporter DATABASE_URL pour pointer sur localhost
export DATABASE_URL="postgresql+asyncpg://netforge:dev@localhost:5432/netforge"
export SESSION_SIGNING_KEY="dev-key-not-for-prod"
export BOOTSTRAP_ADMIN_EMAIL="admin@example.com"

# migrations
alembic upgrade head

# serveur
uvicorn app.main:app --reload --port 8000
```

Puis `curl http://localhost:8000/api/health`.

## Structure

```
app/
├── main.py        # création FastAPI, middlewares, routers
├── config.py      # settings Pydantic (BaseSettings)
├── db.py          # engine async SQLAlchemy, session factory
├── models/        # SQLAlchemy ORM
├── schemas/       # Pydantic request/response (phase 3+)
├── routers/       # endpoints par domaine
├── services/      # logique métier (phase 3+)
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
# appliquer toutes
alembic upgrade head

# créer une nouvelle migration (autogenerate sur les models)
alembic revision --autogenerate -m "description courte"

# revenir à une révision
alembic downgrade -1
```
