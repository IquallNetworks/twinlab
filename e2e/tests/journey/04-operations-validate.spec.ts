import { expect, test } from '@playwright/test'

import { E2E_NET_NAME } from '../../fixtures/fixtures'

// On-demand validation, the facts viewer and the custom-config library —
// the Operations tab against the live lab.
test.describe.configure({ mode: 'serial' })

test('the runtime suite runs green with rendered commands and results', async ({ page }) => {
  test.setTimeout(240_000)
  await page.goto(`/labs/${E2E_NET_NAME}/operations`)

  await page.getByRole('button', { name: 'Run', exact: true }).nth(1).click()
  await expect(page.getByRole('button', { name: 'Running…' })).toBeVisible()
  // Two loopback pings (r1→r3, r3→r1), both green.
  await expect(page.getByText(/2 passed · 0 failed/)).toBeVisible({ timeout: 180_000 })

  // Expand: per-node rows with pass badges and the RENDERED command (facts
  // resolved the loopback address).
  await page.getByRole('button', { name: 'Expand' }).last().click()
  await expect(page.locator('[data-slot="badge"]', { hasText: 'pass' }).first()).toBeVisible()
  await expect(page.getByText(/ping -c 3 -W 2 10\.\d+\.\d+\.\d+/).first()).toBeVisible()
})

test('the facts viewer serves the node namespace', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/operations`)
  await page.getByRole('button', { name: 'Facts' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('Node facts')).toBeVisible()
  // The promised core is visible in the JSON: OSPF router ids exist.
  await expect(dialog.locator('.cm-editor').getByText('"router_id"').first()).toBeVisible({
    timeout: 30_000,
  })
  await page.keyboard.press('Escape')
})

test('custom config lists the built-in template tier', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/operations`)
  const card = page.locator('[data-slot="card"]', { hasText: 'Custom config' }).first()
  await expect(card.locator('[data-slot="badge"]', { hasText: 'built-in' }).first()).toBeVisible()
  await expect(card.getByText('mpls_te')).toBeVisible()
  await expect(card.getByText('ip_sla')).toBeVisible()
})
