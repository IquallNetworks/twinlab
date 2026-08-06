import path from 'node:path'

import { expect, test as setup } from '@playwright/test'

import { E2E_ROOT, stackEnv } from '../lib/env'
import { expectToast } from '../lib/toast'

const env = stackEnv()

// The login surface IS this suite's setup: it asserts the whole page on the
// way in and leaves the admin session behind as storageState for every other
// project.
setup('login page gates, validates and signs in', async ({ page }) => {
  // The auth layout resolves /auth/me in beforeLoad; without a session every
  // authenticated route bounces here.
  await page.goto('/')
  await page.waitForURL('**/login')
  await expect(page).toHaveTitle('Twinlab — Sign in')
  await expect(page.getByRole('heading', { name: 'Sign in to Twinlab' })).toBeAttached()
  await expect(page.locator('[data-slot="card-title"]')).toHaveText('Sign in')
  await expect(page.getByText('Use your Twinlab account credentials.')).toBeVisible()
  await expect(page.getByText('declarative, reproducible network twins')).toBeVisible()

  // Empty submit → both zod field messages.
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText('Username is required')).toBeVisible()
  await expect(page.getByText('Password is required')).toBeVisible()

  // The password reveal toggle flips the input type.
  const password = page.getByLabel('Password', { exact: true })
  await page.getByLabel('Username').fill(env.adminUsername)
  await password.fill('wrong-password')
  await expect(password).toHaveAttribute('type', 'password')
  await page.getByRole('button', { name: 'Show password' }).click()
  await expect(password).toHaveAttribute('type', 'text')
  await page.getByRole('button', { name: 'Hide password' }).click()
  await expect(password).toHaveAttribute('type', 'password')

  // Wrong credentials → the server envelope's message in an error toast.
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expectToast(page, 'invalid credentials')

  // Real credentials → the dashboard, signed in as the bootstrap admin.
  await password.fill(env.adminPassword)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  await expect(page.getByRole('banner').getByText(env.adminUsername, { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()

  await page.context().storageState({ path: path.join(E2E_ROOT, '.auth', 'admin.json') })
})
