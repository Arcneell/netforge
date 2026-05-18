"""FastAPI entry point — wires middleware and routers."""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.config import get_settings
from app.routers import (
    ai,
    audit,
    auth,
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
    subnets,
    switches,
    topology,
    vlans,
)
from app.middleware.rate_limit import WriteRateLimitMiddleware
from app.services.audit import (
    current_request_ip_var,
    current_request_ua_var,
    register_audit_listeners,
)
from app.utils.request import client_ip

logger = logging.getLogger("netforge")


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging(settings.log_level)

    app = FastAPI(
        title="Netforge API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
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
    # topology view fire many GETs per page load.
    app.add_middleware(
        WriteRateLimitMiddleware,
        max_per_window=settings.rate_limit_writes_per_window,
        window_seconds=settings.rate_limit_window_seconds,
    )

    @app.middleware("http")
    async def log_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        start = time.monotonic()

        # Make request metadata visible to the audit-log SQLAlchemy listeners,
        # which fire deep inside the ORM session and have no Request handle.
        # See app/utils/request.py for the trust-order rationale (TL;DR: we
        # rely on nginx's X-Real-IP, never on the client-spoofable XFF chain).
        current_request_ip_var.set(client_ip(request))
        current_request_ua_var.set(request.headers.get("user-agent"))

        response: Response
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.exception(
                "request.error rid=%s %s %s duration_ms=%d",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
            )
            raise
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "request rid=%s %s %s status=%d duration_ms=%d",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        response.headers["x-request-id"] = request_id
        return response

    # Wire ORM event listeners so every mutation produces an audit_log row.
    # Idempotent: safe to call multiple times in tests / reloads.
    register_audit_listeners()

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(sites.router, prefix="/api")
    app.include_router(rooms.router, prefix="/api")
    app.include_router(vlans.router, prefix="/api")
    app.include_router(subnets.router, prefix="/api")
    app.include_router(ips.router, prefix="/api")
    app.include_router(devices.router, prefix="/api")
    app.include_router(switches.router, prefix="/api")
    app.include_router(ports.nested_router, prefix="/api")
    app.include_router(ports.router, prefix="/api")
    app.include_router(links.router, prefix="/api")
    app.include_router(audit.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(topology.router, prefix="/api")
    app.include_router(imports.router, prefix="/api")
    app.include_router(exports.router, prefix="/api")
    app.include_router(ai.router, prefix="/api")

    return app


app = create_app()
