import { expect, test } from '@playwright/test'

/**
 * Topology view smoke test.
 *
 * The Cytoscape canvas renders nodes/edges to a <canvas> element which
 * Playwright can't introspect — so we assert on the side-channel signals
 * instead: the container's accessible label, and the side panel telling us
 * how many nodes were loaded. The empty-state copy must NOT appear; if it
 * does, the API call failed silently or no switches/links are seeded.
 */
test('topology view renders the graph with at least one node', async ({ page }) => {
  await page.goto('/topology')
  await expect(page.getByRole('heading', { name: /topology|topologie/i })).toBeVisible()

  // Canvas wrapper — TopologyCanvas exposes role=img + aria-label.
  await expect(page.getByRole('img', { name: /network topology graph|graphe de topologie/i }))
    .toBeVisible()

  // The empty-state copy is a sentinel — its presence means no data loaded.
  await expect(page.getByText(/no topology to display|aucune topologie à afficher/i))
    .toBeHidden()

  // Layout selector + "Fit to screen" + "Export PNG" buttons are the
  // user-facing toolbar; they only mount once the canvas is ready.
  await expect(page.getByRole('button', { name: /fit to screen|ajuster/i })).toBeEnabled()
  await expect(page.getByRole('button', { name: /export png/i })).toBeEnabled()
})
