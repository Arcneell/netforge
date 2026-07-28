import { expect, test } from '@playwright/test'
import { ensureSubnet } from './seed-helpers'

/**
 * Add an IP via the "next free" flow.
 *
 * Steps a real admin takes:
 *   1. Open the Subnets list.
 *   2. Pick our E2E sandbox subnet (seeded via API at start of test).
 *   3. Click "Next free IP" — the IP form page opens prefilled with the address.
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

  // Open the IP form prefilled with the next free address. Creating is a full
  // page, not a modal — see components/FormPage.vue.
  await page.getByRole('button', { name: /next free|prochaine adresse libre/i }).click()
  await expect(page).toHaveURL(new RegExp(`/subnets/${subnet.id}/ips/new\\?address=`))

  // Status defaults to "Reserved" — switch it to "Assigned".
  //
  // The control is `ui/Select.vue`, a custom listbox rather than a native
  // `<select>` (Chromium on Windows refuses to theme a native option popup,
  // which made it unreadable in dark mode). So `selectOption` doesn't apply:
  // open the combobox and click the option.
  await page.getByRole('combobox', { name: /status|statut/i }).click()
  await page.getByRole('option', { name: /^assigned$|^attribuée$/i }).click()

  await page.getByLabel(/hostname/i).fill(hostname)

  await page.getByRole('button', { name: /^save|^enregistrer/i }).click()

  // On success we land back on the subnet the IP belongs to.
  await expect(page).toHaveURL(new RegExp(`/subnets/${subnet.id}$`))

  // The hostname we just typed should now be visible somewhere on the page —
  // table view shows it as a column; grid view shows it in a hover tooltip
  // (so we toggle to table to make the assertion deterministic).
  await page.getByRole('button', { name: /table view|vue tableau/i }).click()
  await expect(page.getByText(hostname)).toBeVisible()
})
