import { expect, test } from '@playwright/test'

import { E2E_NET_NAME, E2E_NET_NODES } from '../../fixtures/fixtures'
import { expectToast } from '../../lib/toast'

// The deployed lab's runtime surfaces: node table, connect drawer, logs,
// web terminal, per-node power.
test.describe.configure({ mode: 'serial' })

test('the node table reports every container running with its identity', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/nodes`)

  for (const node of E2E_NET_NODES) {
    const row = page.getByRole('row').filter({ hasText: `clab-${E2E_NET_NAME}-${node}` })
    await expect(row).toBeVisible()
    await expect(row.locator('[data-slot="badge"]', { hasText: 'running' })).toBeVisible()
    // Every node owns an address inside the lab's mgmt pool (10.79/16).
    await expect(row.getByText(/^10\.79\.\d+\.\d+$/)).toBeVisible()
  }
  const r1 = page.getByRole('row').filter({ hasText: `clab-${E2E_NET_NAME}-r1` })
  // The pinned local tag (see the catalog's IMAGE_PINS) — proof the pin
  // reaches the actually-deployed container, not just the catalog.
  await expect(r1.getByText('twinlab/vyos:2026.05.30-0046-rolling')).toBeVisible()
  const r3 = page.getByRole('row').filter({ hasText: `clab-${E2E_NET_NAME}-r3` })
  await expect(r3.getByText(/frrouting\/frr/)).toBeVisible()

  // The copy affordance answers with a toast.
  await r1.getByRole('button', { name: /Copy address/ }).click()
  await expectToast(page, 'Copied address')
})

test('the connect drawer serves the SSH recipe with the real address', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/nodes`)
  const r1 = page.getByRole('row').filter({ hasText: `clab-${E2E_NET_NAME}-r1` })
  await r1.getByRole('button', { name: 'Connect' }).click()

  const sheet = page.locator('[data-slot="sheet-content"]')
  await expect(sheet.getByText('Management address')).toBeVisible()
  await expect(sheet.getByText('SSH from your machine')).toBeVisible()
  // The node's mgmt address renders in the drawer, the config-block recipe
  // teaches the jump host, and the one-liner is the ProxyCommand form.
  await expect(sheet.getByText(/^10\.79\.\d+\.\d+$/)).toBeVisible()
  await expect(sheet.getByText('Host twinlab-jump')).toBeVisible()
  // The node alias: an ssh_config entry whose HostName is still the address,
  // so the command names the node while the jump keeps seeing the IP.
  await expect(sheet.getByText(`Host r1.${E2E_NET_NAME}`)).toBeVisible()
  await expect(sheet.getByText(`ProxyJump twinlab-jump`)).toBeVisible()
  await expect(sheet.getByText(`ssh r1.${E2E_NET_NAME}`, { exact: true })).toBeVisible()
  await sheet.getByRole('tab', { name: 'One-liner' }).click()
  await expect(sheet.getByText(/ProxyCommand/)).toBeVisible()
  await page.keyboard.press('Escape')
})

test('the Nodes tab hands out an ssh_config for the whole lab', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/nodes`)
  await page.getByRole('button', { name: 'SSH config', exact: true }).click()

  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText(`SSH config — ${E2E_NET_NAME}`)).toBeVisible()
  await expect(dialog.getByText(`nodes (${E2E_NET_NODES.length})`)).toBeVisible()
  // Every deployed node is aliased, jump-routed, and addressed.
  for (const node of E2E_NET_NODES) {
    await expect(dialog.getByText(`Host ${node}.${E2E_NET_NAME}`)).toBeVisible()
  }
  // The login field rewrites every block, so one edit serves the whole lab.
  await dialog.getByLabel('Node login').fill('vyos')
  await expect(dialog.getByText('User vyos').first()).toBeVisible()

  await dialog.getByRole('button', { name: `Copy nodes (${E2E_NET_NODES.length})` }).click()
  await expectToast(page, `Copied nodes (${E2E_NET_NODES.length})`)
  await page.keyboard.press('Escape')
})

test('logs stream and the web terminal answers a command', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/nodes`)
  const r3 = page.getByRole('row').filter({ hasText: `clab-${E2E_NET_NAME}-r3` })

  await r3.getByRole('button', { name: 'Logs' }).click()
  await expect(page.getByText('Logs — r3')).toBeVisible()
  await expect(page.getByText('last 200 lines')).toBeVisible()
  await expect(page.locator('pre').first()).not.toBeEmpty()
  await page.getByRole('button', { name: 'Refresh' }).click()
  await page.keyboard.press('Escape')

  // The terminal over the shell transport (docker exec — credential-free).
  await r3.getByRole('button', { name: 'Console' }).click()
  await page.getByRole('button', { name: 'shell', exact: true }).click()
  await expect(page.getByText('Connected · shell')).toBeVisible({ timeout: 30_000 })
  // Drive xterm through its hidden helper textarea — page-level keyboard
  // events reach it flakily (the typed text landed but Enter got lost).
  const termInput = page.locator('.xterm-helper-textarea')
  await termInput.pressSequentially('hostname')
  await termInput.press('Enter')
  await expect(page.locator('.xterm')).toContainText('r3', { timeout: 15_000 })
  await page.keyboard.press('Escape')
})

test('per-node power: stop and restart a host', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/nodes`)
  const h2 = page.getByRole('row').filter({ hasText: `clab-${E2E_NET_NAME}-h2` })

  await h2.getByRole('button', { name: 'Actions' }).click()
  await page.getByRole('menuitem', { name: 'Stop', exact: true }).click()
  await expect(h2.locator('[data-slot="badge"]', { hasText: 'exited' })).toBeVisible({
    timeout: 60_000,
  })

  await h2.getByRole('button', { name: 'Actions' }).click()
  await page.getByRole('menuitem', { name: 'Start', exact: true }).click()
  await expect(h2.locator('[data-slot="badge"]', { hasText: 'running' })).toBeVisible({
    timeout: 60_000,
  })
})
