import { expect, test } from '@playwright/test'
import { seedTopologyPair } from './seed-helpers'

/**
 * Topology view smoke test.
 *
 * The Cytoscape canvas renders nodes/edges to a <canvas> element which
 * Playwright can't introspect — so we assert on the side-channel signals
 * instead: the container's accessible label and the toolbar's enabled
 * buttons. The empty-state copy must NOT appear; if it does, no graph
 * data made it through.
 *
 * Seeds its own pair of linked switches via the API so the test runs on a
 * fresh DB (Codex P2 on PR #7).
 */
// Skipped: /topology currently serves `TopologyWipView.vue` while the graph is
// redesigned, so there is no canvas, no layout selector and no export button to
// assert on. `TopologyView.vue` and this spec both stay in place and the skip
// comes off together with the route.
test.skip('topology view renders the graph with at least one node', async ({ page, request }) => {
  await seedTopologyPair(request)
  await page.goto('/topology')
  await expect(page.getByRole('heading', { name: /topology|topologie/i })).toBeVisible()

  // Canvas wrapper — TopologyCanvas exposes role=img + aria-label.
  await expect(
    page.getByRole('img', { name: /network topology graph|graphe de topologie/i }),
  ).toBeVisible()

  // The empty-state copy is a sentinel — its presence means no data loaded.
  await expect(page.getByText(/no topology to display|aucune topologie à afficher/i)).toBeHidden()

  // Layout selector + "Fit to screen" + "Export PNG" buttons are the
  // user-facing toolbar; they only mount once the canvas is ready.
  await expect(page.getByRole('button', { name: /fit to screen|ajuster/i })).toBeEnabled()
  await expect(page.getByRole('button', { name: /export png/i })).toBeEnabled()
})
