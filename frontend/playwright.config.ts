import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright config — covers the 3 critical user flows called out in
 * docs/10-roadmap.md (Phase 10): add an IP, create a switch with auto-
 * generated ports, and view the topology.
 *
 * Assumes the dev stack is already up:
 *   docker compose -f docker-compose.dev.yml up -d
 *
 * Auth uses the "dev" provider (passwordless local admin). A storage-state
 * file is produced by `auth.setup.ts` and reused by every spec — re-running
 * the suite never burns a fresh OAuth round-trip.
 *
 * To run:
 *   npm run test:e2e         # headless, CI-style
 *   npm run test:e2e:ui      # interactive watch mode
 *
 * The runtime browser is Microsoft Edge (channel: msedge). It ships with
 * Windows and macOS and is signed, sidestepping the AV friction the bundled
 * chrome-headless-shell hits on some corporate machines. If Edge isn't
 * present, install with:
 *   npx playwright install msedge
 * or fall back to system Chrome via PLAYWRIGHT_CHANNEL=chrome.
 *
 * See e2e/README.md for the Docker-only alternative (avoids host Node).
 */
export default defineConfig({
  testDir: './e2e',
  // Workers serialised — every test mutates shared DB state (subnets, IPs,
  // switches). Parallelism would need namespacing by worker index, which
  // isn't worth the complexity for 3 specs.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    // Runtime channel applied to BOTH the setup project and the spec project
    // — keeping it in `use` means the auth setup uses Edge too, avoiding the
    // Defender-blocks-headless-shell trap on Windows.
    channel: process.env.PLAYWRIGHT_CHANNEL ?? 'msedge',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
    },
    {
      // We use Microsoft Edge as the runtime browser rather than Playwright's
      // bundled chrome-headless-shell. On Windows with Defender, the bundled
      // headless binary is sometimes blocked at launch (unsigned, auto-
      // downloaded). Edge ships with the OS, is signed, and runs identical
      // Chromium under the hood — same rendering, no AV friction.
      // Override with PLAYWRIGHT_CHANNEL=chrome if Edge isn't available.
      name: 'edge',
      use: {
        ...devices['Desktop Edge'],
        channel: process.env.PLAYWRIGHT_CHANNEL ?? 'msedge',
        storageState: '.playwright-auth.json',
      },
      dependencies: ['setup'],
    },
  ],
})
