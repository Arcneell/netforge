"""Guards the runtime versions that are pinned in more than one place.

Node, Python and PostgreSQL each have their major pinned across several files
that must agree, and Dependabot can only see some of them:

    node 22      frontend/Dockerfile, docker-compose.dev.yml   <- Dependabot sees
                 .github/workflows/ci.yml x3                   <- it does not
    python 3.12  backend/Dockerfile                            <- sees
                 ci.yml x4, pyproject requires-python          <- does not
    postgres 16  docker-compose.yml, docker-compose.dev.yml    <- sees
                 ci.yml x2 (integration + e2e services)        <- does not

PR #155 shipped that gap: it moved `docker-compose.dev.yml` to `node:26-alpine`
and left the other four pins on 22, contradicting the comment in that very file
requiring them to match. PR #156 moved both compose files to `postgres:18-alpine`
while CI kept proving the SQL against 16 — and 18 cannot start on a 16 data
directory at all. Both were closed rather than merged.

`.github/dependabot.yml` now ignores those majors so a partial bump is never
opened automatically. This is the other half: it fails when a *human* moves one
pin and forgets the rest, which no `ignore` entry can prevent.

Same rationale and shape as `test_compose_env_passthrough.py` — an invariant that
lives across files, is invisible from any one of them, and has already been
broken once.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Only backend/ is bind-mounted into the dev container, so a pytest run from
# inside it cannot see the repo root. CI checks out the whole tree.
pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "docker-compose.yml").is_file(),
    reason="repo root not reachable (running from inside the backend container)",
)


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _majors(pattern: str, text: str) -> list[str]:
    """Major component of every version this pattern captures."""
    return [m.group(1).split(".")[0] for m in re.finditer(pattern, text)]


def test_node_major_agrees_everywhere() -> None:
    """The dev container, the production build stage and every CI job must run
    the same Node major, or `npm ci` resolves a different tree in CI than the
    one the image actually ships."""
    found: dict[str, list[str]] = {
        ".github/workflows/ci.yml": _majors(
            r'node-version:\s*"(\d[\d.]*)"', _read(".github/workflows/ci.yml")
        ),
        "frontend/Dockerfile": _majors(r"FROM node:(\d[\d.]*)-", _read("frontend/Dockerfile")),
        "docker-compose.dev.yml": _majors(
            r"image:\s*node:(\d[\d.]*)-", _read("docker-compose.dev.yml")
        ),
    }
    _assert_single_major("Node", found)


def test_python_major_agrees_everywhere() -> None:
    """The backend image, every CI job and `requires-python` must agree. A
    mismatch means the wheels resolved in CI are not the wheels installed in the
    image."""
    found: dict[str, list[str]] = {
        ".github/workflows/ci.yml": [
            ".".join(v.split(".")[:2])
            for v in re.findall(
                r'python-version:\s*"(\d+\.\d+)"', _read(".github/workflows/ci.yml")
            )
        ],
        "backend/Dockerfile": re.findall(r"FROM python:(\d+\.\d+)-", _read("backend/Dockerfile")),
        "backend/pyproject.toml": re.findall(
            r'requires-python\s*=\s*">=(\d+\.\d+)"', _read("backend/pyproject.toml")
        ),
    }
    # Compared at minor precision on purpose: CPython's compatibility boundary is
    # the minor (3.12 vs 3.13), not the major.
    _assert_single_major("Python", found)


def test_postgres_major_agrees_everywhere() -> None:
    """Both compose files and both CI service containers must run the same
    PostgreSQL major. CI is what proves the GiST exclusions, the subnet
    containment triggers and the INET/CIDR operators work; if production runs a
    different major, none of that evidence applies to it."""
    found: dict[str, list[str]] = {
        ".github/workflows/ci.yml": _majors(
            r"image:\s*postgres:(\d[\d.]*)-", _read(".github/workflows/ci.yml")
        ),
        "docker-compose.yml": _majors(
            r"image:\s*postgres:(\d[\d.]*)-", _read("docker-compose.yml")
        ),
        "docker-compose.dev.yml": _majors(
            r"image:\s*postgres:(\d[\d.]*)-", _read("docker-compose.dev.yml")
        ),
    }
    _assert_single_major("PostgreSQL", found)


def _assert_single_major(runtime: str, found: dict[str, list[str]]) -> None:
    empty = sorted(path for path, versions in found.items() if not versions)
    assert not empty, (
        f"{runtime} version pin not found in {empty} — the pattern in this test "
        "went stale, which means the guard silently stopped guarding. Fix the "
        "pattern rather than deleting the entry."
    )

    distinct = {version for versions in found.values() for version in versions}
    assert len(distinct) == 1, (
        f"{runtime} is pinned to more than one version across the repo: "
        f"{ {path: versions for path, versions in found.items()} }. "
        "Every one of these has to move in the same change — see the header of "
        ".github/dependabot.yml for why Dependabot cannot do it for you."
    )


def test_ignored_runtimes_are_still_multi_pin() -> None:
    """A stale `ignore` in dependabot.yml is worse than none: it silently blocks
    a bump that would now be complete on its own.

    Each runtime whose majors we ignore must genuinely still be pinned in a file
    Dependabot cannot reach. When that stops being true, drop the ignore.
    """
    import yaml

    config = yaml.safe_load(_read(".github/dependabot.yml"))
    ignored = {
        entry["dependency-name"]
        for update in config["updates"]
        for entry in (update.get("ignore") or [])
    }

    ci = _read(".github/workflows/ci.yml")
    # What makes each runtime un-bumpable by Dependabot: a pin inside ci.yml,
    # which no ecosystem in dependabot.yml covers.
    unreachable_pins = {
        "node": r'node-version:\s*"\d',
        "python": r'python-version:\s*"\d',
        "postgres": r"image:\s*postgres:\d",
    }

    for name in sorted(ignored):
        pattern = unreachable_pins.get(name)
        assert pattern is not None, (
            f"dependabot.yml ignores {name!r} majors but this test does not know why. "
            "Add it to `unreachable_pins` with the pin Dependabot cannot see, or "
            "drop the ignore."
        )
        assert re.search(pattern, ci), (
            f"dependabot.yml still ignores {name!r} majors, but ci.yml no longer "
            "pins it — so Dependabot could now open a complete bump. Remove the "
            "ignore entry."
        )
