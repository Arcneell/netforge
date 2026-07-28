import { expect, test } from '@playwright/test'

/**
 * Create a switch and confirm its ports are auto-generated.
 *
 * The most distinctive behaviour of the Switch entity vs Devices is that
 * creating one triggers backend auto-generation of N empty ports — this test
 * verifies that contract end-to-end.
 */
test('admin can create a switch and see its ports auto-generated', async ({ page }) => {
  const name = `E2E-SW-${Date.now()}`
  const portCount = 4

  await page.goto('/switches')
  await expect(page.getByRole('heading', { name: /switches|commutateurs/i })).toBeVisible()

  // Open the "New switch" form. Creating is a full page, not a modal — see
  // views/forms/SwitchFormView.vue. On a fresh DB the CTA appears twice
  // (page header + empty state), so pick the first match.
  await page
    .getByRole('button', { name: /new switch|nouveau commutateur/i })
    .first()
    .click()
  await expect(page).toHaveURL(/\/switches\/new/)

  // Query by accessible name (getByRole), not getByLabel: the FormField
  // label's raw text carries the required marker ("Name *"), which breaks
  // anchored label matching, while the computed accessible name is clean.
  // Anchored exact match: /^nom/ alone would also match "Nombre de ports".
  await page.getByRole('textbox', { name: /^name$|^nom$/i }).fill(name)
  // port_count is the field whose immutability the form warns about — fill
  // with a small N so the rack view renders quickly.
  await page.getByRole('spinbutton', { name: /port count|nombre de ports/i }).fill(String(portCount))
  await page.getByRole('button', { name: /^save$|^enregistrer$/i }).click()

  // On success we land back on the switches list; the new row appears.
  await expect(page).toHaveURL(/\/switches$/)
  const newRow = page.getByRole('row').filter({ hasText: name })
  await expect(newRow).toBeVisible()

  // Drill into the switch detail.
  await newRow.click()
  await expect(page).toHaveURL(/\/switches\/\d+/)

  // The rack view should show exactly `portCount` numbered cells. The
  // "Ports" stat in the header also reports the count — easier and more
  // stable than counting DOM cells.
  await expect(page.getByText(new RegExp(`0\\s*(of|sur|/)\\s*${portCount}`, 'i'))).toBeVisible()
})
