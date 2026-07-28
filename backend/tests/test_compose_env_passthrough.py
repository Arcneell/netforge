"""Guards the .env.example -> docker-compose -> backend container chain.

Every knob documented in .env.example is only real if compose actually forwards
it into the backend service. Three regressions have shipped from this exact gap
(LOG_FORMAT, then AI_DRAFTS_ENABLED / AI_SCHEDULER_ENABLED): the variable was
documented, the Settings field existed and gated real behaviour, but neither
compose file listed it, so operators silently got the default.

The invariant: if .env.example documents a variable AND app.config.Settings
reads it, both compose files must pass it to `backend.environment`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.dev.yml")

# Only backend/ is bind-mounted into the dev container, so a pytest run from
# inside it cannot see the repo root. CI checks out the whole tree and runs
# from backend/, which is where this guard is meant to fire.
pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "docker-compose.yml").is_file(),
    reason="repo root not reachable (running from inside the backend container)",
)

# Documented in .env.example but deliberately NOT forwarded to the backend
# service. Each entry needs a reason, otherwise it is a bug in disguise.
NOT_FORWARDED = {
    # Compose builds DATABASE_URL itself from POSTGRES_*; the .env value only
    # applies when the backend runs outside Docker.
    "DATABASE_URL",
    # Consumed by the postgres service, not the backend.
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    # Host-side port publishing only; never reaches the container.
    "POSTGRES_HOST_PORT",
    # Build/dev-server-time variable for the SPA, not a backend Settings field.
    "VITE_AUTH_PROVIDER",
    # docker-compose.yml hardcodes "true" so a .env typo cannot downgrade
    # cookie security in production; the dev stack relies on the backend's
    # own False default. Intentionally not overridable in either file.
    "SESSION_COOKIE_SECURE",
}

# Additional per-file exemptions, on top of NOT_FORWARDED.
NOT_FORWARDED_PER_FILE = {
    "docker-compose.yml": {
        # The dev auth provider cannot run in production at all: the factory
        # raises when SESSION_COOKIE_SECURE is true, which this file forces.
        # Forwarding its fake-account settings would only invite misuse.
        "DEV_ADMIN_EMAIL",
        "DEV_ADMIN_NAME",
    },
    "docker-compose.dev.yml": set(),
}


def _documented_vars() -> set[str]:
    """Uncommented NAME=... assignments in .env.example."""
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))


def _backend_env_keys(compose_file: str) -> set[str]:
    spec = yaml.safe_load((REPO_ROOT / compose_file).read_text(encoding="utf-8"))
    env = spec["services"]["backend"]["environment"]
    # Both files use the mapping form; support the list form too so a future
    # reformat doesn't turn this guard into a false pass.
    if isinstance(env, list):
        return {item.split("=", 1)[0] for item in env}
    return set(env)


@pytest.mark.parametrize("compose_file", COMPOSE_FILES)
def test_documented_backend_settings_are_forwarded(compose_file: str) -> None:
    settings_vars = {name.upper() for name in Settings.model_fields}
    exempt = NOT_FORWARDED | NOT_FORWARDED_PER_FILE[compose_file]
    expected = (_documented_vars() & settings_vars) - exempt
    missing = sorted(expected - _backend_env_keys(compose_file))
    assert not missing, (
        f"{compose_file} does not pass these documented settings to the backend "
        f"container, so setting them in .env has no effect: {missing}"
    )


def test_not_forwarded_allowlist_has_no_dead_entries() -> None:
    """A stale exemption would hide a real passthrough gap."""
    documented = _documented_vars()
    allowlisted = NOT_FORWARDED | set().union(*NOT_FORWARDED_PER_FILE.values())
    stale = sorted(name for name in allowlisted if name not in documented)
    assert not stale, f"exemption lists name variables absent from .env.example: {stale}"
