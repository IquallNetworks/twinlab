import { expect, test } from '@playwright/test'

import { E2E_NET_NAME } from '../../fixtures/fixtures'
import { editorText, setEditorText } from '../../lib/editor'
import { expectToast } from '../../lib/toast'

// Definition drift, the Changes diff, redeploy, and whole-lab power.
test.describe.configure({ mode: 'serial' })

test('editing the deployed definition raises the drift badge and diff', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/build`)
  await page.getByRole('button', { name: 'Edit the definition as text' }).click()
  const editor = page.locator('.cm-editor')
  await expect(editor).toBeVisible()

  // Append one more stub link — a small, valid, visible change.
  const current = await editorText(editor)
  await setEditorText(editor, current + '- name: extra\n  r2:\n')
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
  await expect(page.locator('[data-slot="badge"]', { hasText: 'deployed' })).toBeVisible({
    timeout: 700_000,
  })
  await expect(page.locator('[data-slot="badge"]', { hasText: 'drifted' })).toHaveCount(0)
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
