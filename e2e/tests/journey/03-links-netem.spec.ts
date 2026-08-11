import { expect, test } from '@playwright/test'

import { E2E_NET_LINKS, E2E_NET_NAME } from '../../fixtures/fixtures'
import { clickEdge } from '../../lib/canvas'

// The link table, bidirectional link impairment, the per-interface
// unidirectional form, and the canvas edge panel.
test.describe.configure({ mode: 'serial' })

test('the links table lists every named link with live state', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/nodes`)
  const links = page.locator('[data-slot="card"]', { hasText: 'Links' }).first()

  for (const name of E2E_NET_LINKS) {
    await expect(links.getByText(name, { exact: true })).toBeVisible()
  }
  // Endpoints read node:iface, and live columns are present.
  await expect(links.getByText('r1:eth1')).toBeVisible()
  await expect(links.getByRole('columnheader', { name: 'State' })).toBeVisible()
  await expect(links.getByRole('columnheader', { name: 'Impairment' })).toBeVisible()
  // The OSPF triangle is up end to end.
  await expect(links.locator('[data-slot="badge"]', { hasText: 'up' }).first()).toBeVisible()
})

test('link impairment applies both ways and reads back as a summary', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/nodes`)
  const links = page.locator('[data-slot="card"]', { hasText: 'Links' }).first()
  const row = links.getByRole('row').filter({ hasText: 'core-a' })

  await row.getByRole('button', { name: 'Impair' }).click()
  await expect(page.getByText('Impairment — both directions')).toBeVisible()
  await expect(
    page.getByText('Applied to each direction: 50 ms delay means 50 ms per direction (~100 ms round trip).'),
  ).toBeVisible()

  await page.getByLabel('Delay (ms)').fill('50')
  await page.getByRole('button', { name: 'Apply' }).click()
  await expect(page.getByRole('button', { name: 'Applied' })).toBeVisible({ timeout: 30_000 })
  await expect(row.getByText('50 ms')).toBeVisible()
  await expect(links.getByLabel('impaired').first()).toBeVisible()
})

test('the canvas edge panel exposes the impairment editor', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/overview`)
  const canvas = page.getByRole('application', { name: 'Lab topology canvas' })
  await expect(canvas.locator('.react-flow__edge').first()).toBeVisible()

  // Each link wears the subnet netlab assigned it — the p2p edges as an edge
  // label, the LAN's under its hub. Only the server link table knows these,
  // so they appear once it resolves.
  await expect(canvas.locator('.react-flow__edge-textwrapper').first()).toContainText(/\d+\.\d+\.\d+\.\d+\/\d+/)

  // Click an edge ON its path — the bottom panel opens with per-endpoint
  // state (node:iface pairs). Retried: the live canvas reseeds once when the
  // links query resolves, which can move the edge between the point
  // computation and the click.
  await expect(async () => {
    await clickEdge(page, canvas.locator('.react-flow__edge').first())
    await expect(page.getByText(/eth\d/).first()).toBeVisible({ timeout: 2_000 })
  }).toPass({ timeout: 20_000 })
})

test('interface netem is unidirectional and clears from the link row', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/nodes`)

  // The Interfaces card shapes ONE direction of one node.
  const interfaces = page.locator('[data-slot="card"]', { hasText: 'Interfaces' }).first()
  await expect(interfaces.getByRole('combobox')).toBeVisible()
  await expect(interfaces.getByRole('row').first()).toBeVisible()

  // Clear the link impairment set above; the summary empties.
  const links = page.locator('[data-slot="card"]', { hasText: 'Links' }).first()
  const row = links.getByRole('row').filter({ hasText: 'core-a' })
  await row.getByRole('button', { name: 'Impair' }).click()
  await page.getByRole('button', { name: 'Clear' }).click()
  await expect(row.getByText('50 ms')).toHaveCount(0, { timeout: 30_000 })
  await expect(links.getByLabel('impaired')).toHaveCount(0)
})
