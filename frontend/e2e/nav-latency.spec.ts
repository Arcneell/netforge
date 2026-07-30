import { test, expect } from '@playwright/test'

/**
 * Measures what the user actually complained about: the gap between clicking a
 * nav entry and the new page being on screen.
 *
 * This is a diagnostic, not a gate — it prints timings and only asserts a
 * deliberately loose ceiling, because wall-clock on a dev server sharing a
 * laptop with Docker is noisy and a tight bound here would flake for reasons
 * that have nothing to do with the code. Run it by hand when touching routing or
 * `composables/useRoutePrefetch.ts`:
 *
 *   npx playwright test e2e/nav-latency.spec.ts --reporter=list
 *
 * It is excluded from the CI suite for the same reason (see `testIgnore` in
 * playwright.config.ts).
 */

const TARGETS = [
  { label: 'Subnets', path: '/subnets' },
  { label: 'VLANs', path: '/vlans' },
  { label: 'Switches', path: '/switches' },
  { label: 'Devices', path: '/devices' },
  { label: 'Topology', path: '/topology' },
]

test('nav clicks land quickly', async ({ page }) => {
  await page.goto('/')
  // The dashboard is the landing route; wait for the shell rather than any
  // particular widget so slow API calls don't get counted as nav latency.
  await expect(page.locator('nav[aria-label], aside, header').first()).toBeVisible()

  // Give the idle prefetcher its window — that is the path a real user takes
  // (the app has been open a moment before they click anything).
  await page.waitForTimeout(2500)

  const results: string[] = []

  for (const target of TARGETS) {
    const link = page.locator(`a[href="${target.path}"]`).first()
    await expect(link).toBeVisible()

    const started = Date.now()
    await link.click()
    // URL flips the instant Vue Router commits the navigation, which is exactly
    // what was blocked on the lazy import. Waiting on the URL rather than on
    // page content keeps API latency out of the number.
    await page.waitForURL(`**${target.path}`, { timeout: 15_000 })
    const committed = Date.now() - started

    results.push(`${target.label.padEnd(10)} ${committed}ms`)
    expect(committed, `${target.label} navigation should not take seconds`).toBeLessThan(3000)

    await page.goBack()
    await page.waitForURL('**/', { timeout: 15_000 })
  }

  console.log('\nNavigation commit latency:\n' + results.map((r) => '  ' + r).join('\n') + '\n')
})
