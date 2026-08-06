import { expect, test } from '@playwright/test'

import { stackEnv } from '../../lib/env'
import { expectToast } from '../../lib/toast'

const env = stackEnv()

// A throwaway but valid ed25519 public key (public halves are not secrets).
const TEST_PUBLIC_KEY =
  'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGr5GBbNxkmw83Sq96MKCjZQSVuG3GM+ochfLhw/Swhb e2e@test'

test('password change: wrong current inline, real change keeps the session', async ({ page }) => {
  await page.goto('/account')
  await expect(page.getByRole('heading', { name: 'Account' })).toBeVisible()

  await page.getByRole('button', { name: 'Change password' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Current password').fill('wrong-password')
  await dialog.getByLabel('New password', { exact: true }).fill('e2e-temp-password')
  await dialog.getByLabel('Confirm new password').fill('e2e-temp-password')
  await dialog.getByRole('button', { name: 'Change password' }).click()
  // A 403 lands INLINE under the current-password field, not as a toast.
  await expect(dialog.getByText('current password is incorrect')).toBeVisible()

  // Real change → toast; the calling session survives, others are revoked.
  await dialog.getByLabel('Current password').fill(env.adminPassword)
  await dialog.getByRole('button', { name: 'Change password' }).click()
  await expectToast(page, 'Password changed — your other sessions were signed out')
  await expect(page.getByRole('heading', { name: 'Account' })).toBeVisible()

  // Change it straight back so the suite's credentials stay true.
  await page.getByRole('button', { name: 'Change password' }).click()
  const again = page.getByRole('dialog')
  await again.getByLabel('Current password').fill('e2e-temp-password')
  await again.getByLabel('New password', { exact: true }).fill(env.adminPassword)
  await again.getByLabel('Confirm new password').fill(env.adminPassword)
  await again.getByRole('button', { name: 'Change password' }).click()
  await expectToast(page, 'Password changed — your other sessions were signed out')
})

test('API keys: create, one-time reveal, revoke', async ({ page }) => {
  await page.goto('/account')
  await expect(page.getByText('No API keys.')).toBeVisible()

  await page.getByRole('button', { name: 'New API key' }).click()
  await page.getByLabel('Name').fill('e2e-ci')
  await page.getByRole('button', { name: 'Create' }).click()
  await expect(
    page.getByText('This key is shown only once — store it now. It is kept hashed server-side.'),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Done' }).click()

  const row = page.getByRole('row').filter({ hasText: 'e2e-ci' })
  await expect(row.getByText('never')).toBeVisible()

  await row.getByRole('button').last().click()
  await expect(page.getByText('Revoke e2e-ci?')).toBeVisible()
  await expect(page.getByText('Callers using this key lose access immediately.')).toBeVisible()
  // The confirm action reads Delete even for a revoke.
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click()
  await expectToast(page, 'API key revoked')
  await expect(page.getByText('No API keys.')).toBeVisible()
})

test('SSH keys: jump recipe, register (invalid + valid), generate, delete', async ({ page }) => {
  await page.goto('/account')

  // The advertised jump host renders the ~/.ssh/config recipe.
  await expect(page.getByText('Host twinlab-jump')).toBeVisible()
  await expect(page.getByText('Port 2422')).toBeVisible()
  await expect(page.getByText('User jump')).toBeVisible()
  await expect(page.getByText('No SSH keys.')).toBeVisible()

  // Garbage is rejected with the server's message.
  await page.getByRole('button', { name: 'Register key' }).click()
  let dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name').fill('e2e-key')
  await dialog.getByLabel('Public key').fill('not-a-key')
  await dialog.getByRole('button', { name: 'Register' }).click()
  await expect(page.locator('[data-sonner-toast][data-type="error"]')).toBeVisible()
  await dialog.getByLabel('Public key').fill(TEST_PUBLIC_KEY)
  await dialog.getByRole('button', { name: 'Register' }).click()
  await expectToast(page, /Registered e2e-key \(SHA256:/)

  const row = page.getByRole('row').filter({ hasText: 'e2e-key' })
  await expect(row.getByText('ssh-ed25519')).toBeVisible()
  await expect(row.getByText('never')).toBeVisible()

  // Server-side generation: private key revealed once + downloadable.
  await page.getByRole('button', { name: 'Generate key' }).click()
  dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name').fill('e2e-gen')
  await dialog.getByRole('button', { name: 'Generate' }).click()
  const downloadPromise = page.waitForEvent('download')
  await dialog.getByRole('button', { name: 'Download' }).click()
  expect((await downloadPromise).suggestedFilename()).toBe('e2e-gen.key')
  await dialog.getByRole('button', { name: 'Done' }).click()

  // Delete both; revocation copy names the consequence.
  for (const name of ['e2e-key', 'e2e-gen']) {
    await page
      .getByRole('row')
      .filter({ hasText: name })
      .getByRole('button')
      .last()
      .click()
    await expect(page.getByText(`Delete ${name}?`)).toBeVisible()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click()
    await expectToast(page, 'SSH key deleted')
  }
  await expect(page.getByText('No SSH keys.')).toBeVisible()
})
