import { expect, test } from '@playwright/test'

import { FAST_LAB } from '../../fixtures/fixtures'
import { flowNode, flowNodes } from '../../lib/canvas'
import { expectToast } from '../../lib/toast'

test.describe.configure({ mode: 'serial' })

test('a node saves into the template library and stamps from the Add menu', async ({ page }) => {
  await page.goto(`/labs/${FAST_LAB}/build`)
  const canvas = page.getByRole('region', { name: 'Topology builder canvas' })
  await expect(canvas).toBeVisible()

  // r1 (vyos, from the e2e-net definition) becomes a node template.
  await flowNode(canvas, 'r1').click()
  await page.locator('aside').getByRole('button', { name: 'Save as template' }).click()
  await expect(page.getByText('Save node as template')).toBeVisible()
  await page.getByLabel('Template name').fill('e2e-router')
  await page.getByLabel('Description').fill('vyos core router, OSPF via lab defaults')
  await page.getByRole('button', { name: 'Save template' }).click()
  await expectToast(page, "Node template e2e-router saved — it's now in the Add menu")

  // The palette lists it (name + device) and stamping adds a node.
  const nodesBefore = await flowNodes(canvas).count()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  const item = page.getByRole('menuitem', { name: /e2e-router/ })
  await expect(item).toContainText('vyos')
  await item.click()
  await expect(flowNodes(canvas)).toHaveCount(nodesBefore + 1)
  await expect(page.getByText('unsaved changes')).toBeVisible()
  await page.getByRole('button', { name: 'Discard' }).click()
})

test('publishing the lab serves it as a network template', async ({ page }) => {
  await page.goto(`/labs/${FAST_LAB}/overview`)
  await page.getByRole('button', { name: 'Lab actions' }).click()
  await page.getByRole('menuitem', { name: 'Use as a template…' }).click()
  await expect(page.getByText(`Use ${FAST_LAB} as a template`)).toBeVisible()
  await page.getByLabel('Library description').fill('the e2e suite’s OSPF triangle')
  await page.getByRole('button', { name: 'Publish' }).click()
  await expectToast(page, `${FAST_LAB} is published as a network template`)
  await expect(page.locator('[data-slot="badge"]', { hasText: 'template' })).toBeVisible()

  // The menu entry now reads as settings.
  await page.getByRole('button', { name: 'Lab actions' }).click()
  await expect(page.getByRole('menuitem', { name: 'Template settings…' })).toBeVisible()
  await page.keyboard.press('Escape')
})

test('a new lab starts from the published template', async ({ page }) => {
  await page.goto('/labs')
  await page.getByRole('button', { name: 'New lab' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name').fill('e2e-seeded')

  // The Start-from list carries both tiers with their suffixes.
  await dialog.getByLabel('Start from').click()
  await expect(page.getByRole('option', { name: /mpls-l3vpn/ })).toContainText('· built-in')
  const published = page.getByRole('option', { name: new RegExp(FAST_LAB) })
  await expect(published).toContainText('· published lab')
  await published.click()
  await expect(dialog.getByText('the e2e suite’s OSPF triangle')).toBeVisible()

  await dialog.getByRole('button', { name: 'Create' }).click()
  await expectToast(page, `Lab e2e-seeded created from ${FAST_LAB} — review, then deploy`)
  await page.waitForURL('**/labs/e2e-seeded/overview')

  // The seeded definition renders: e2e-net's 5 devices + the LAN hub.
  const canvas = page.getByRole('application', { name: 'Lab topology canvas' })
  await expect(flowNodes(canvas)).toHaveCount(6)
})

test('withdrawing removes the template and the seeded lab deletes', async ({ page }) => {
  await page.goto(`/labs/${FAST_LAB}/overview`)
  await page.getByRole('button', { name: 'Lab actions' }).click()
  await page.getByRole('menuitem', { name: 'Template settings…' }).click()
  await page.getByRole('button', { name: 'Withdraw' }).click()
  await expectToast(page, `${FAST_LAB} withdrawn from the template library`)
  await expect(page.locator('[data-slot="badge"]', { hasText: 'template' })).toHaveCount(0)

  await page.goto('/labs')
  await page.getByRole('button', { name: 'Delete e2e-seeded' }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click()
  await expectToast(page, 'Deleted e2e-seeded')
})
