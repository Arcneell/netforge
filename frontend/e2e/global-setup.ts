/**
 * `playwright.config.ts` used to ship with no `webServer` block: point
 * Playwright at a stack that isn't running and every spec fails one by one
 * with an opaque `net::ERR_CONNECTION_REFUSED` — no hint that the fix is
 * "start the dev stack", not "fix the test".
 *
 * This is a `globalSetup` rather than a `webServer` entry because the dev
 * stack here is docker-compose (Postgres + backend + Vite), not a single
 * process Playwright could spawn/reap itself — pinging it and failing fast
 * with a clear instruction is the honest equivalent.
 *
 * CI (`.github/workflows/ci.yml`, job `e2e`) starts the backend and Vite
 * itself as background processes and already waits for both with a
 * `curl --retry` step before invoking Playwright, so this check is a no-op
 * there (`process.env.CI` is set on every GitHub Actions runner).
 */
const BACKEND_HEALTH_URL = 'http://localhost:8000/api/health'

async function isUp(url: string): Promise<boolean> {
  try {
    const res = await fetch(url, { method: 'GET' })
    return res.ok
  } catch {
    return false
  }
}

export default async function globalSetup(): Promise<void> {
  if (process.env.CI) return

  // Same default as the `use.baseURL` in playwright.config.ts.
  const frontendUrl = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
  const [backendUp, frontendUp] = await Promise.all([isUp(BACKEND_HEALTH_URL), isUp(frontendUrl)])

  if (backendUp && frontendUp) return

  const missing = [
    !backendUp ? `backend (${BACKEND_HEALTH_URL})` : null,
    !frontendUp ? `frontend (${frontendUrl})` : null,
  ]
    .filter(Boolean)
    .join(' and ')

  throw new Error(
    `\n\nE2E setup check failed: ${missing} not reachable.\n\n` +
      `Start the dev stack first:\n\n` +
      `    docker compose -f docker-compose.dev.yml up -d\n\n` +
      `Then re-run \`npm run test:e2e\`.\n`,
  )
}
