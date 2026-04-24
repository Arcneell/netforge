# Dockerfile backend — image slim Python 3.12 + app FastAPI
#
# Build depuis la racine du repo :
#   docker build -t netforge-backend:dev ./backend
#
# Ou via docker compose (cf docker-compose.dev.yml / docker-compose.yml à la racine).

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dépendances système minimales (psycopg/asyncpg n'en ont pas besoin côté runtime,
# mais curl sert pour le HEALTHCHECK et tini pour PID 1 propre).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tini \
 && rm -rf /var/lib/apt/lists/*

# Install des dépendances Python en premier (couche cachable)
COPY pyproject.toml README.md ./
# trick pour que pip install -e puisse résoudre les metadata avant que le code soit copié
RUN mkdir -p app && touch app/__init__.py && pip install -e . && rm -rf app

# Copie du code
COPY . .

# Utilisateur non-root
RUN useradd --system --uid 1000 --create-home --shell /bin/bash netforge \
 && chown -R netforge:netforge /app
USER netforge

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/health >/dev/null || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
