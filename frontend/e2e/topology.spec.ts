import { expect, test, type Page } from '@playwright/test'
import { cleanupSeededSwitches, seedTopologyPair } from './seed-helpers'

// seedTopologyPair creates a fresh, timestamped pair of switches on every run
// (see seed-helpers.ts) — clean them up so repeated runs don't leave orphan
// switches (and their auto-generated ports) in the dev database.
test.afterAll(async ({ request }) => {
  await cleanupSeededSwitches(request)
})

/**
 * Topology view smoke tests.
 *
 * Cytoscape paints to a <canvas> Playwright cannot introspect, and the canvas
 * is `aria-hidden` besides — it is a decorative duplicate of the List view. So
 * the graph assertions are on the side channels (toolbar, empty-state
 * sentinel), and the data assertions run against the List view, which renders
 * the same nodes and edges as real tables. That split is the point: anything a
 * test cannot reach here is also something a keyboard user cannot reach.
 */

/** Switch to the list and return the row for `name`, scrolled into view.
 *
 * A dev database holds a few hundred rows, so a seeded switch is far below the
 * fold — `toBeVisible()` on it fails for scroll position rather than for
 * anything the test cares about.
 */
async function listRow(page: Page, name: string) {
  await page.getByRole('button', { name: /^(List|Liste)$/ }).click()
  const row = page.getByText(name, { exact: true }).first()
  await row.scrollIntoViewIfNeeded()
  return row
}

test('graph view loads with a working toolbar and real data', async ({ page, request }) => {
  await seedTopologyPair(request)
  await page.goto('/topology')

  await expect(page.getByRole('heading', { name: /topology|topologie/i })).toBeVisible()

  // The empty-state copy is a sentinel — its presence means no data loaded.
  await expect(page.getByText(/nothing to map yet|rien à cartographier/i)).toBeHidden()

  // The toolbar mounts with the canvas.
  await expect(page.getByRole('button', { name: /fit to screen|ajuster/i })).toBeEnabled()
  await expect(page.getByRole('button', { name: /export png|exporter en png/i })).toBeEnabled()

  // The permanent legend is part of the redesign: media styles carry meaning,
  // so the key has to be on screen while scanning, not only on selection.
  await expect(page.getByText(/^(Legend|Légende)$/)).toBeVisible()
})

test('list view exposes the same graph as keyboard-reachable tables', async ({ page, request }) => {
  const { a, b } = await seedTopologyPair(request)
  await page.goto('/topology')

  const rowA = await listRow(page, a.name)
  await expect(rowA).toBeVisible()

  // Selecting a row drives the inspector — the same interaction the canvas
  // offers via tap, available here without a pointer.
  await rowA.click()
  // By name, not by tag: the app sidebar is an <aside> too, and an unnamed
  // `locator('aside')` picks that one.
  const inspector = page.getByRole('complementary', {
    name: /selection details|détails de la sélection/i,
  })
  await expect(inspector).toContainText(a.name)

  // The neighbour list is a graph edge rendered as a control: following it
  // moves the inspector to the other end of the seeded link.
  await inspector.getByRole('button', { name: new RegExp(b.name, 'i') }).click()
  await expect(inspector).toContainText(b.name)
})

test('turning devices off refetches without dropping switches', async ({ page, request }) => {
  const { a } = await seedTopologyPair(request)
  await page.goto('/topology')

  const devicesToggle = page.getByRole('checkbox')
  await expect(devicesToggle).toBeChecked()
  await devicesToggle.uncheck()

  // The switch-only view must still hold the seeded switch. A filter that
  // dropped switches along with devices is the regression worth catching.
  await expect(page.getByText(/nothing to map yet|rien à cartographier/i)).toBeHidden()
  await expect(await listRow(page, a.name)).toBeVisible()
})
