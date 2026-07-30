"""Guards the runtime versions that are pinned in more than one place.

Node, Python and PostgreSQL each have their major pinned across several files
that must agree, and Dependabot can only see some of them:

    node 22      frontend/Dockerfile, docker-compose.dev.yml   <- Dependabot sees
                 .github/workflows/ci.yml x3                   <- it does not
    python 3.12  backend/Dockerfile                            <- sees
                 ci.yml x4, pyproject requires-python          <- does not
    postgres 16  docker-compose.yml, docker-compose.dev.yml    <- sees
                 ci.yml x2 (integration + e2e services)        <- does not
    redis 8      docker-compose.yml, docker-compose.dev.yml    <- sees
                 ci.yml x1 (integration service)               <- does not

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
        # `@types/node` is a Node pin too: it declares the API surface the
        # compiler believes exists. Ahead of the runtime, TypeScript accepts
        # calls that are not there — and the types are the thing that would
        # otherwise have caught it. PR #178 proposed 22 -> 26 on its own.
        "frontend/package.json": _majors(
            r'"@types/node":\s*"[^\d]*(\d[\d.]*)"', _read("frontend/package.json")
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


def test_redis_major_agrees_everywhere() -> None:
    """Both compose files and CI's integration service container must run the
    same Redis major.

    This one is here because the guard missed it once. When `ignore` was first
    written, redis was left out on the claim it was "pinned here only" — but the
    PR that added the cache also added a `redis:N-alpine` service container to
    ci.yml. PR #173 then moved both compose files to 8-alpine and left CI proving
    the rate-limit Lua script, the atomic INCR and the EXPIRE semantics against 7.
    """
    found: dict[str, list[str]] = {
        ".github/workflows/ci.yml": _majors(
            r"image:\s*redis:(\d[\d.]*)-", _read(".github/workflows/ci.yml")
        ),
        "docker-compose.yml": _majors(r"image:\s*redis:(\d[\d.]*)-", _read("docker-compose.yml")),
        "docker-compose.dev.yml": _majors(
            r"image:\s*redis:(\d[\d.]*)-", _read("docker-compose.dev.yml")
        ),
    }
    _assert_single_major("Redis", found)


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


# Everything ignored in dependabot.yml, classified by *why*. A stale `ignore` is
# worse than none — it silently blocks a bump that would now be fine — so each
# entry has to declare which kind of stale it can become.
#
# MULTI_PIN: ignored because the version is also pinned somewhere Dependabot
# cannot reach, making any PR it opens partial. The pattern is that unreachable
# pin. Goes stale when the pin disappears, which the test below detects.
MULTI_PIN_IGNORES = {
    "node": r'node-version:\s*"\d',
    "python": r'python-version:\s*"\d',
    "postgres": r"image:\s*postgres:\d",
    "redis": r"image:\s*redis:\d",
    # `@types/node` has no pin of its own in ci.yml — it is ignored because it
    # must track the Node *runtime*, whose `node-version` entries here
    # Dependabot cannot see. Same unreachable pin, one step removed.
    "@types/node": r'node-version:\s*"\d',
}

# UPSTREAM_BLOCKED: ignored because no version of it can be installed with the
# rest of the tree, for reasons outside this repo. Goes stale when upstream
# publishes a compatible release — which cannot be checked without hitting the
# network, so it is not asserted here. The `ignore` comment in dependabot.yml
# names the exact condition to watch for instead.
UPSTREAM_BLOCKED_IGNORES = {
    # openapi-typescript and typescript-eslint both cap typescript below 6.1 on
    # their latest releases. See the comment on the ignore entry.
    "typescript",
    # `pydantic` pins `pydantic-core` to an exact version, so it can only move
    # when pydantic does — at which point pip-compile picks the matching core on
    # its own. Proposed and refused three times (#158, #179, #194).
    "pydantic-core",
}


def test_every_ignore_is_classified() -> None:
    """A new `ignore` must say which kind of stale it can become.

    This exists so the next person to add one has to think about how it gets
    removed. An ignore with no removal condition is a permanent silent block.
    """
    import yaml

    config = yaml.safe_load(_read(".github/dependabot.yml"))
    ignored = {
        entry["dependency-name"]
        for update in config["updates"]
        for entry in (update.get("ignore") or [])
    }

    known = set(MULTI_PIN_IGNORES) | UPSTREAM_BLOCKED_IGNORES
    unclassified = sorted(ignored - known)
    assert not unclassified, (
        f"dependabot.yml ignores {unclassified} but this test does not know why. "
        "Add each to MULTI_PIN_IGNORES (with the pin Dependabot cannot see) or to "
        "UPSTREAM_BLOCKED_IGNORES (with the blocking peer named in the config "
        "comment), or drop the ignore."
    )

    stale = sorted(known - ignored)
    assert not stale, (
        f"{stale} are classified here but no longer ignored in dependabot.yml. "
        "Drop them from this test so it stops describing a rule that is gone."
    )


def test_ignored_runtimes_are_still_multi_pin() -> None:
    """Each multi-pin ignore must still have its unreachable pin.

    When ci.yml stops pinning a runtime, Dependabot could open a complete bump
    and the ignore should go.
    """
    import yaml

    config = yaml.safe_load(_read(".github/dependabot.yml"))
    ignored = {
        entry["dependency-name"]
        for update in config["updates"]
        for entry in (update.get("ignore") or [])
    } & set(MULTI_PIN_IGNORES)

    ci = _read(".github/workflows/ci.yml")
    unreachable_pins = MULTI_PIN_IGNORES

    # Classification itself is asserted by `test_every_ignore_is_classified`;
    # this one only checks that each classified pin still exists.
    for name in sorted(ignored):
        assert re.search(unreachable_pins[name], ci), (
            f"dependabot.yml still ignores {name!r} majors, but ci.yml no longer "
            "pins it — so Dependabot could now open a complete bump. Remove the "
            "ignore entry."
        )
