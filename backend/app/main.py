"""FastAPI entry point — wires middleware and routers."""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import __version__
from app.config import get_settings
from app.logging_config import configure_logging, request_id_var
from app.middleware.rate_limit import WriteRateLimitMiddleware
from app.routers import (
    ai,
    audit,
    auth,
    cables,
    devices,
    exports,
    health,
    imports,
    ips,
    links,
    ports,
    rooms,
    search,
    sites,
    snapshots,
    subnets,
    switches,
    topology,
    vlans,
    vrfs,
    webhooks,
)
from app.services.audit import (
    current_request_ip_var,
    current_request_ua_var,
    register_audit_listeners,
)
from app.services.webhooks import (
    dispatch_committed_in_background,
    take_pending,
)
from app.utils.request import client_ip

logger = logging.getLogger("netforge")


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Start the AI scheduler at process boot, cancel it on shutdown.

    The scheduler is opt-in: rows in `ai_schedules` ship with `enabled=false`,
    so this is a no-op for fresh installs. Test environments override the
    lifespan by passing their own `lifespan=` argument when building the app.
    """
    from app.services.ai.scheduler import start_scheduler, stop_scheduler

    start_scheduler()
    try:
        yield
    finally:
        await stop_scheduler()


class _RequestLogMiddleware:
    """Raw ASGI request logger.

    Why not `@app.middleware("http")`: that decorator wraps the callable in
    Starlette's `BaseHTTPMiddleware`, which bridges the response through an
    anyio memory stream. The bridge silently breaks `text/event-stream`
    streaming on `/api/ai/query/stream` — SSE chunks pile up until the
    response ends, so the Ask AI page renders the answer all at once
    instead of token-by-token. Operating at the raw ASGI layer pipes
    `(scope, receive, send)` straight through, preserving streaming.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        # Propagate to the ContextVar so every log line emitted while handling
        # this request — not just the final access line — carries the rid.
        request_id_var.set(request_id)
        start = time.monotonic()

        # Make request metadata visible to the audit-log SQLAlchemy listeners,
        # which fire deep inside the ORM session and have no Request handle.
        # See app/utils/request.py for the trust-order rationale (TL;DR: we
        # rely on nginx's X-Real-IP, never on the client-spoofable XFF chain).
        current_request_ip_var.set(client_ip(request))
        current_request_ua_var.set(request.headers.get("user-agent"))

        status_holder = {"code": 0}

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = int(message.get("status", 0))
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # Crash path: drop anything that was still PENDING (the session
            # rolled back, so subscribers must not see those events).
            # Committed events, however, correspond to rows already in the
            # DB — the audit_log row exists, the entity is there. Dropping
            # them on a post-commit failure (response-serialisation error,
            # ResponseModel validation failure, anything that runs after
            # `await db.commit()`) silently desyncs webhook subscribers
            # from the actual DB state. Dispatch them as we would on the
            # success path.
            take_pending()
            dispatch_committed_in_background()
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.exception(
                "request.error rid=%s %s %s duration_ms=%d",
                request_id,
                scope.get("method"),
                scope.get("path"),
                duration_ms,
                extra={
                    "event": "request.error",
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "duration_ms": duration_ms,
                },
            )
            raise
        # Dispatch events that survived a session commit. Anything still in
        # `_pending` belongs to a flush that never committed (e.g. CSV import
        # `dry_run=true`) — drop it. The HTTP status no longer gates dispatch
        # because session lifecycle is the source of truth (see services.webhooks).
        take_pending()
        dispatch_committed_in_background()
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "request rid=%s %s %s status=%d duration_ms=%d",
            request_id,
            scope.get("method"),
            scope.get("path"),
            status_holder["code"],
            duration_ms,
            extra={
                "event": "request",
                "method": scope.get("method"),
                "path": scope.get("path"),
                "status": status_holder["code"],
                "duration_ms": duration_ms,
            },
        )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title="Netforge API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=_lifespan,
    )

    # Short-lived signed cookie used by authlib to store the OAuth `state`
    # between the authorize redirect and the callback. Distinct from the
    # long-lived `netforge_session` cookie that identifies the logged-in user.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_signing_key,
        session_cookie="netforge_oauth_state",
        same_site="lax",
        https_only=settings.session_cookie_secure,
        max_age=600,  # 10 minutes — only needs to outlive the OAuth round-trip
    )

    if settings.cors_origins_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Rate-limit write methods. Reads are never throttled — dashboards and the
    # topology view fire many GETs per page load. The counter lives in
    # Postgres so every worker/replica shares one budget; `engine=None`
    # (RATE_LIMIT_STORE=memory) falls back to the legacy per-process window.
    from app.db import engine as db_engine

    app.add_middleware(
        WriteRateLimitMiddleware,
        max_per_window=settings.rate_limit_writes_per_window,
        window_seconds=settings.rate_limit_window_seconds,
        engine=db_engine if settings.rate_limit_store == "database" else None,
    )

    app.add_middleware(_RequestLogMiddleware)

    # Wire ORM event listeners so every mutation produces an audit_log row.
    # Idempotent: safe to call multiple times in tests / reloads.
    register_audit_listeners()

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(sites.router, prefix="/api")
    app.include_router(rooms.router, prefix="/api")
    app.include_router(vlans.router, prefix="/api")
    app.include_router(vrfs.router, prefix="/api")
    app.include_router(subnets.router, prefix="/api")
    app.include_router(ips.router, prefix="/api")
    app.include_router(devices.router, prefix="/api")
    app.include_router(switches.router, prefix="/api")
    app.include_router(ports.nested_router, prefix="/api")
    app.include_router(ports.router, prefix="/api")
    app.include_router(links.router, prefix="/api")
    app.include_router(cables.router, prefix="/api")
    app.include_router(cables.nested_router, prefix="/api")
    app.include_router(audit.router, prefix="/api")
    app.include_router(snapshots.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(topology.router, prefix="/api")
    app.include_router(imports.router, prefix="/api")
    app.include_router(exports.router, prefix="/api")
    app.include_router(ai.router, prefix="/api")
    app.include_router(webhooks.router, prefix="/api")

    return app


app = create_app()
