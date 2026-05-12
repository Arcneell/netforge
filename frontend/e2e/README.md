# Playwright E2E

Three smoke tests covering the critical user flows called out in
`docs/10-roadmap.md`:

1. **`add-ip.spec.ts`** — admin opens a subnet, hits "Next free IP", saves a
   new IP with a hostname.
2. **`create-switch.spec.ts`** — admin creates a switch and confirms the
   backend auto-generated its ports.
3. **`topology.spec.ts`** — `/topology` renders the Cytoscape canvas with
   data (no empty state).

## Running

The dev stack must be up first:

```sh
docker compose -f docker-compose.dev.yml up -d
```

```sh
cd frontend
npm install                          # picks up @playwright/test
npx playwright install msedge        # one-time; or `chromium`
npm run test:e2e                     # headless
npm run test:e2e:ui                  # interactive watch mode
```

### Why Edge as the default channel

The bundled `chrome-headless-shell.exe` is an unsigned auto-downloaded
binary that Windows Defender (and several corporate EDRs) flag at launch,
giving a `spawn EPERM` error. Microsoft Edge is signed and pre-installed
on Windows 11; same Chromium engine, no AV friction.

Set `PLAYWRIGHT_CHANNEL=chrome` to use system Chrome instead, or
`PLAYWRIGHT_CHANNEL=chromium` to use the bundled binary (works on
machines without Defender blocks).

## Auth

`auth.setup.ts` runs once and saves the session cookie to
`.playwright-auth.json`. Specs reuse this state and never hit `/api/auth/*`
again. The setup relies on `AUTH_PROVIDER=dev` in the backend — it
passwordlessly stamps an admin session.

The auth file is gitignored. Delete it if the session expires or you
change auth providers.

## DB state

Tests create rows with timestamped names (`e2e-host-<ts>`, `E2E-SW-<ts>`)
so they're re-runnable against a long-lived dev database without
collisions. They never clean up — small leak per run, easy to wipe with
the seed script when the DB gets crowded.
