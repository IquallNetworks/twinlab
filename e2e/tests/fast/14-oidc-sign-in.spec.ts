import { expect, test, type Browser, type Page } from '@playwright/test'

import { stackEnv } from '../../lib/env'
import { expectToast } from '../../lib/toast'

// Sign-in through an OIDC provider (contract delta 33), end to end in a real
// browser: an admin registers the stack's TEST provider — Dex, layered on by
// stack.sh from oidc-test/compose.yaml — and fresh browsers sign in through
// the login page's button and Dex's own login form.
test.describe.configure({ mode: 'serial' })

const env = stackEnv()
const CALLBACK = `${env.baseUrl}/api/v1/auth/oidc/dex/callback`

// Dex's static users all share Dex's example password (oidc-test/compose.yaml).
const DEX_PASSWORD = 'password'

async function signInThroughDex(browser: Browser, email: string): Promise<Page> {
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto('/login')
  await page.getByRole('link', { name: 'Sign in with Dex' }).click()
  // Dex's own login form — the provider's page, not Twinlab's.
  await page.locator('input[name="login"]').fill(email)
  await page.locator('input[name="password"]').fill(DEX_PASSWORD)
  await page.locator('button[type="submit"]').click()
  return page
}

test('an admin registers Dex as a sign-in provider', async ({ page }) => {
  await page.goto('/sign-in-providers')
  await expect(page).toHaveTitle('Twinlab — Sign-in providers')
  await expect(page.getByRole('heading', { name: 'Sign-in providers' })).toBeVisible()

  await page.getByRole('button', { name: 'Add provider' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name', { exact: true }).fill('dex')
  await dialog.getByLabel('Button label', { exact: true }).fill('Dex')
  await dialog.getByLabel('Issuer', { exact: true }).fill(env.dexIssuer)
  await dialog.getByLabel('Client ID', { exact: true }).fill('twinlab')
  await dialog.getByLabel('Client secret value', { exact: true }).fill('twinlab-test-secret')
  await dialog.getByLabel('Create accounts', { exact: true }).check()
  await dialog.getByRole('button', { name: 'Add provider' }).click()
  await expectToast(page, 'Added Dex')

  // The redirect URI an admin registers at the provider, ready to copy.
  await expect(page.getByText(CALLBACK)).toBeVisible()
})

test('a new person signs in through Dex and gets an account', async ({ browser }) => {
  const page = await signInThroughDex(browser, 'alice@example.com')
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  // A provider-created account is greeted by the name the provider gave.
  await expect(page.getByRole('main').getByText('alice', { exact: true })).toBeVisible()
  await page.context().close()
})

test('the created account is linked to the provider', async ({ page }) => {
  await page.goto('/users')
  const row = page.getByRole('row').filter({ hasText: 'alice@example.com' })
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: 'Profile' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('Linked sign-in providers')).toBeVisible()
  await expect(dialog.getByText('dex', { exact: true })).toBeVisible()
})

test('a refused sign-in explains itself on the login page', async ({ browser, page }) => {
  // Creation off: a stranger now has nowhere to land.
  await page.goto('/sign-in-providers')
  await page.getByRole('button', { name: 'Edit' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Create accounts', { exact: true }).uncheck()
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expectToast(page, 'Saved Dex')

  const stranger = await signInThroughDex(browser, 'bob@example.com')
  await expect(stranger).toHaveURL(/\/login\?oidc_error=oidc_no_account/)
  await expect(
    stranger.getByText('There is no Twinlab account for you yet, and this provider does not create one.'),
  ).toBeVisible()
  // The password form is still there: provider sign-in adds a way in, it
  // replaces nothing.
  await expect(stranger.getByLabel('Username', { exact: true })).toBeVisible()
  await stranger.context().close()
})
