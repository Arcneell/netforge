import { expect, test } from '@playwright/test'
import { ensureSubnet } from './seed-helpers'

/**
 * Add an IP via the "next free" flow.
 *
 * Steps a real admin takes:
 *   1. Open the Subnets list.
 *   2. Pick our E2E sandbox subnet (seeded via API at start of test).
 *   3. Click "Next free IP" — the editor opens prefilled with the address.
 *   4. Fill a hostname and save.
 *   5. The new IP should appear in the table view of the subnet detail.
 *
 * Names are timestamp-suffixed so the test is rerunnable against a long-lived
 * dev database. The subnet is seeded idempotently via the API so the spec
 * works on a fresh Alembic-only DB (Codex P1 on PR #7).
 */
test('admin can add an IP via the subnet next-free flow', async ({ page, request }) => {
  const hostname = `e2e-host-${Date.now()}`
  const subnet = await ensureSubnet(request)

  // Drill straight into the seeded subnet — no dependency on existing rows.
  await page.goto(`/subnets/${subnet.id}`)
  await expect(page).toHaveURL(new RegExp(`/subnets/${subnet.id}$`))

  // Open the IP editor prefilled with the next free address.
  await page.getByRole('button', { name: /next free|prochaine adresse libre/i }).click()

  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  // Status defaults to "Reserved" — switch it to "Assigned" via the option
  // value (locale-independent: the underlying IpStatus enum is English).
  await dialog.getByLabel(/status|statut/i).selectOption('assigned')
  await dialog.getByLabel(/hostname/i).fill(hostname)

  await dialog.getByRole('button', { name: /^save|^enregistrer/i }).click()

  // Editor closes on success.
  await expect(dialog).not.toBeVisible()

  // The hostname we just typed should now be visible somewhere on the page —
  // table view shows it as a column; grid view shows it in a hover tooltip
  // (so we toggle to table to make the assertion deterministic).
  await page.getByRole('button', { name: /table view|vue tableau/i }).click()
  await expect(page.getByText(hostname)).toBeVisible()
})
