# Contributing to Netforge

Thanks for your interest. Contributions of any size are welcome — bug reports, doc fixes, tests, or features. For anything non-trivial, please open an issue first so we can align on the approach before you invest time in a PR.

## Development environment

The easiest way to hack on the backend is to run Postgres in Docker and the app in a local venv with `--reload`:

```bash
# 1. start Postgres in a container
docker compose -f docker-compose.dev.yml up -d postgres

# 2. backend venv
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 3. point the app at the container
export DATABASE_URL="postgresql+asyncpg://netforge:dev@localhost:5432/netforge"
export SESSION_SIGNING_KEY="dev-key-not-for-prod"
export BOOTSTRAP_ADMIN_EMAIL="admin@example.com"

# 4. apply migrations, then run
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Alternatively, run everything under Docker:

```bash
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml exec backend alembic upgrade head
```

Smoke-test: `curl http://localhost:8000/api/health` should return `{"status":"ok","db":"ok",...}`.

## Tests and lint

```bash
cd backend
pytest                      # run the suite
ruff check .                # lint
ruff format --check .       # formatting check
ruff format .               # apply formatting
```

CI must be green before a PR is merged. Any new business rule (GiST constraint, trigger, service) ships with a `pytest` test.

## Ground rules

1. **Small, focused PRs** — one PR, one intent. Easier to review, easier to revert.
2. **Tests** — every new invariant or business rule comes with a test. Migrations with DB-level constraints (GiST, triggers, check constraints) are tested against a real Postgres, not mocked.
3. **Migrations** — never modify the schema by hand. Use `alembic revision --autogenerate -m "short message"`, then review the generated SQL and edit it if needed. Downgrade path must be implemented.
4. **Security** — the rules in [docs/11-security.md](docs/11-security.md) are non-negotiable: strict CSP, audit log on every mutation, `SameSite=Lax` cookies, parameterized SQL, no `v-html` on user input, secrets in env only.
5. **No scope creep** — hold the v1 / v2 line documented in [docs/10-roadmap.md](docs/10-roadmap.md). Nice-to-haves go in the v2 backlog, not the MVP.

## Commit messages

Short imperative subject line (under 70 characters), blank line, optional body explaining *why*. Reference issues with `#N` when relevant.

```
Add CSV dry-run mode for IP import

Allows validating an upload without persisting rows. Returns a per-row
report with counts and error details. Closes #42.
```

## Reporting security issues

Please do **not** open a public issue for security vulnerabilities. Use GitHub's [private security advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) feature instead.

## Code of conduct

Be respectful. Disagree with ideas, not people. No harassment, no personal attacks. Maintainers reserve the right to remove comments, commits, or contributors that breach this.

## License

By contributing, you agree that your contributions will be licensed under the project's [MIT license](LICENSE).
