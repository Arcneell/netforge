import { expect, test as setup } from '@playwright/test'

const AUTH_FILE = '.playwright-auth.json'

/**
 * Sign in once via the dev auth provider, then persist the session cookie
 * for every spec to reuse. With AUTH_PROVIDER=dev the backend's /login
 * endpoint 302s straight to /callback which sets `netforge_session` — no
 * UI interaction required.
 */
setup('authenticate as dev admin', async ({ page }) => {
  await page.goto('/api/auth/login')
  // Callback redirects to "/" after stamping the cookie; if we land there
  // (and not back on /login), we're authenticated.
  await expect(page).toHaveURL(/\/$/)
  // Sanity-check the cookie made it into the context.
  const cookies = await page.context().cookies()
  expect(cookies.some((c) => c.name === 'netforge_session')).toBe(true)
  await page.context().storageState({ path: AUTH_FILE })
})
