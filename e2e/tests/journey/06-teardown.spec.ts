import { expect, test } from '@playwright/test'

import { E2E_NET_NAME } from '../../fixtures/fixtures'
import { expectToast } from '../../lib/toast'

// The lab comes down: destroy (record survives), then delete (record gone);
// history and fleet figures stay honest throughout.
test.describe.configure({ mode: 'serial' })

test('destroy tears the containers down but keeps the record', async ({ page }) => {
  test.setTimeout(420_000)
  await page.goto(`/labs/${E2E_NET_NAME}/overview`)
  await page.getByRole('button', { name: 'Lab actions' }).click()
  await page.getByRole('menuitem', { name: 'Destroy' }).click()
  await expect(page.getByText(`Destroy ${E2E_NET_NAME}?`)).toBeVisible()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Destroy' }).click()

  // The toast lands only when the awaited destroy job finishes.
  await expectToast(page, `Destroyed ${E2E_NET_NAME}`, { timeout: 300_000 })
  await expect(page.locator('[data-slot="badge"]', { hasText: 'destroyed' })).toBeVisible({
    timeout: 60_000,
  })

  // The nodes tab reports the destroyed state, not an empty lie.
  await page.goto(`/labs/${E2E_NET_NAME}/nodes`)
  await expect(page.getByText('No running nodes (destroyed).')).toBeVisible()

  // Jobs history survives destroy: the deploys and the destroy all list
  // (job rows are buttons named "<kind> <status>, open details").
  await page.goto(`/labs/${E2E_NET_NAME}/operations`)
  const history = page.locator('[data-slot="card"]', { hasText: 'Job history' }).first()
  await expect(
    history.getByRole('button', { name: 'destroy succeeded, open details' }).first(),
  ).toBeVisible()
  await expect(
    history.getByRole('button', { name: 'deploy succeeded, open details' }).first(),
  ).toBeVisible()
})

test('delete removes the record; the fleet reflects the end state', async ({ page }) => {
  await page.goto('/labs')
  const row = page.getByRole('row').filter({ hasText: E2E_NET_NAME })
  await expect(row.locator('[data-slot="badge"]', { hasText: 'destroyed' })).toBeVisible()
  await page.getByRole('button', { name: `Delete ${E2E_NET_NAME}` }).click()
  await expect(page.getByText(`Delete ${E2E_NET_NAME}?`)).toBeVisible()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click()
  await expectToast(page, `Deleted ${E2E_NET_NAME}`)
  await expect(page.getByRole('link', { name: E2E_NET_NAME })).toHaveCount(0)

  // Dashboard: the remaining records are the fast tier's two labs, nothing
  // deployed, nothing running.
  await page.goto('/')
  await expect(page.getByRole('link', { name: E2E_NET_NAME })).toHaveCount(0)
  const deployedTile = page.locator('div:has(> span:text-is("deployed"))').locator('span').nth(1)
  await expect(deployedTile).toHaveText('0')
  const nodesTile = page.locator('div:has(> span:text-is("nodes running"))').locator('span').nth(1)
  await expect(nodesTile).toHaveText('0/0')
})
