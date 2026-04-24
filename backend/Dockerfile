# Backend Dockerfile — slim Python 3.12 image + FastAPI app
#
# Build from the repo root:
#   docker build -t netforge-backend:dev ./backend
#
# Or via docker compose (see docker-compose.dev.yml / docker-compose.yml at the repo root).

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Minimal system deps (psycopg/asyncpg need nothing at runtime,
# but curl is used by HEALTHCHECK and tini gives us a clean PID 1).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tini \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first (cacheable layer)
COPY pyproject.toml README.md ./
# Trick so `pip install -e` can read the package metadata before the code is copied in.
RUN mkdir -p app && touch app/__init__.py && pip install -e . && rm -rf app

# Copy the source tree
COPY . .

# Non-root user
RUN useradd --system --uid 1000 --create-home --shell /bin/bash netforge \
 && chown -R netforge:netforge /app
USER netforge

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/health >/dev/null || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
