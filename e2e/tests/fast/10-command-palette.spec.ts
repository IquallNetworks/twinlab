import { expect, test } from '@playwright/test'

import { FAST_LAB } from '../../fixtures/fixtures'
import { stackEnv } from '../../lib/env'

const env = stackEnv()

test('the palette navigates pages and labs, and reports no matches', async ({ page }) => {
  await page.goto('/')
  // Wait for the shell (the palette's own header button) before pressing the
  // shortcut — the window listener mounts with it.
  await expect(page.getByRole('button', { name: 'Command palette' })).toBeVisible()
  await page.keyboard.press('ControlOrMeta+k')
  const palette = page.getByRole('dialog')
  const input = palette.getByPlaceholder('Go to a page or lab…')
  await expect(input).toBeVisible()

  // Page navigation group.
  for (const item of ['Dashboard', 'Labs', 'Jobs', 'Users', 'Groups', 'Account']) {
    await expect(palette.getByRole('option', { name: item, exact: true })).toBeAttached()
  }

  // Fuzzy lab jump: the labs list loads on open.
  await input.fill(FAST_LAB)
  await palette.getByRole('option', { name: new RegExp(FAST_LAB) }).click()
  await page.waitForURL(`**/labs/${FAST_LAB}/overview`)

  // Garbage → the empty state.
  await page.keyboard.press('ControlOrMeta+k')
  await page.getByPlaceholder('Go to a page or lab…').fill('zzzzzz')
  await expect(page.getByText('Nothing matches.')).toBeVisible()
  await page.keyboard.press('Escape')
})

test('palette sign-out ends the session (fresh context, not the shared one)', async ({
  browser,
}) => {
  // Signing out revokes the SERVER session; a fresh UI login here keeps the
  // suite's shared storageState session alive.
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto('/login')
  await page.getByLabel('Username').fill(env.adminUsername)
  await page.getByLabel('Password', { exact: true }).fill(env.adminPassword)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

  await page.keyboard.press('ControlOrMeta+k')
  await page.getByRole('option', { name: 'Sign out' }).click()
  await page.waitForURL('**/login')
  await expect(page.getByText('Use your Twinlab account credentials.')).toBeVisible()

  // The session really is gone: an authenticated route bounces back.
  await page.goto('/labs')
  await page.waitForURL('**/login')
  await context.close()
})
