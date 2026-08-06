import { expect, test } from '@playwright/test'

import { E2E_NET_NAME } from '../../fixtures/fixtures'
import { expectToast } from '../../lib/toast'

// Definition drift, the Changes diff, redeploy, and whole-lab power.
test.describe.configure({ mode: 'serial' })

test('editing the deployed definition raises the drift badge and diff', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/build`)
  await page.getByRole('button', { name: 'Edit the definition as text' }).click()
  const editor = page.locator('.cm-editor')
  await expect(editor).toBeVisible()

  // Add one more stub link INSIDE the links block — the stored doc ends with
  // the server-pinned name/addressing keys, so a document-end append would
  // land outside the list. Anchor on the last link's endpoint line (sink's
  // `r1: null`), scrolled into render range first (CodeMirror virtualizes).
  const content = editor.locator('.cm-content')
  await content.click()
  await content.press('ControlOrMeta+End')
  const anchor = editor.locator('.cm-line', { hasText: 'r1: null' }).last()
  await anchor.click()
  await page.keyboard.press('End')
  await page.keyboard.insertText('\n- name: extra\n  r2:')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expectToast(page, `Definition saved. Deploy ${E2E_NET_NAME} to apply it.`)

  // The header badge and the definition card's Changes view flag the drift.
  await expect(page.locator('[data-slot="badge"]', { hasText: 'drifted' })).toBeVisible()
  await page.goto(`/labs/${E2E_NET_NAME}/overview`)
  await expect(page.getByText('drifted since deploy')).toBeVisible()
  await page.getByRole('tab', { name: 'Changes' }).click()
  await expect(page.getByText('What changed since the last deploy (deployed → stored).')).toBeVisible()
  await expect(page.getByText('+ - name: extra')).toBeVisible()
  await expect(page.getByText('+   r2:')).toBeVisible()
})

test('redeploying clears the drift', async ({ page }) => {
  test.setTimeout(900_000)
  await page.goto(`/labs/${E2E_NET_NAME}/overview`)
  await page.getByRole('button', { name: 'Redeploy' }).click()
  await expect(page.getByText(`Deploy ${E2E_NET_NAME}?`)).toBeVisible()
  // No config push this time — the drift mechanics are what's under test.
  await page.getByRole('dialog').getByRole('button', { name: 'Redeploy' }).click()
  await expect(page.locator('[data-slot="badge"]', { hasText: 'deploying' })).toBeVisible()
  await expect(page.getByRole('main').locator('[data-slot="badge"]').first()).toHaveText(
    /deployed$/,
    { timeout: 300_000 },
  )
  await expect(page.locator('[data-slot="badge"]', { hasText: 'drifted' })).toHaveCount(0)
  // The badge flips when the CONTAINERS are up; the job runs on (bridge
  // prune, snapshot write). Wait it out, or the teardown's destroy submits
  // into the job mutex and 409s job_in_flight.
  await expect(page.getByText('Last operation:')).toBeVisible({ timeout: 60_000 })
  await expect(page.locator('[data-slot="badge"]', { hasText: 'succeeded' })).toBeVisible({
    timeout: 600_000,
  })
})

test('whole-lab power: stop everything, start it back, save config', async ({ page }) => {
  test.setTimeout(420_000)
  await page.goto(`/labs/${E2E_NET_NAME}/nodes`)

  await page.getByRole('button', { name: 'Lab actions' }).click()
  await page.getByRole('menuitem', { name: 'Stop', exact: true }).click()
  await expect(page.locator('[data-slot="badge"]', { hasText: 'exited' }).first()).toBeVisible({
    timeout: 180_000,
  })
  await expect(page.locator('[data-slot="badge"]', { hasText: 'running' })).toHaveCount(0, {
    timeout: 180_000,
  })

  await page.getByRole('button', { name: 'Lab actions' }).click()
  await page.getByRole('menuitem', { name: 'Start', exact: true }).click()
  await expect(page.locator('[data-slot="badge"]', { hasText: 'running' }).first()).toBeVisible({
    timeout: 180_000,
  })

  // Save-config persists the running state; the server's message toasts.
  await page.getByRole('button', { name: 'Lab actions' }).click()
  await page.getByRole('menuitem', { name: 'Save config' }).click()
  await expect(page.locator('[data-sonner-toast]').first()).toBeVisible({ timeout: 120_000 })
})
