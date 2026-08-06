import { expect, test, type Browser, type Page } from '@playwright/test'

import { FAST_LAB, VIEWER } from '../../fixtures/fixtures'
import { selectOption } from '../../lib/radix'
import { expectToast } from '../../lib/toast'

// Role-gated affordances actually hidden or shown: a second context signs in
// as the limited e2e-viewer (created in 02) and sees the consumer's app.
test.describe.configure({ mode: 'serial' })

async function viewerPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto('/login')
  await page.getByLabel('Username').fill(VIEWER.username)
  await page.getByLabel('Password', { exact: true }).fill(VIEWER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  return page
}

test('the viewer dashboard hides every admin affordance', async ({ browser }) => {
  const page = await viewerPage(browser)

  await expect(page.getByRole('main').getByText(VIEWER.username, { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'New lab' })).toHaveCount(0)
  await expect(page.getByText('Administration')).toHaveCount(0)
  await expect(page.getByText('Nothing has been shared with you yet —')).toBeVisible()

  const nav = page.getByRole('navigation')
  await expect(nav.getByRole('link', { name: 'Users', exact: true })).toHaveCount(0)
  await expect(nav.getByRole('link', { name: 'Groups', exact: true })).toHaveCount(0)

  // The route exists but the backend refuses — an honest error, never an
  // empty list.
  await page.goto('/users')
  await expect(page.getByText('missing permission: user:manage')).toBeVisible()
  await expect(page.getByText('no users')).toHaveCount(0)

  // No create/import affordances on the labs page either.
  await page.goto('/labs')
  await expect(page.getByRole('button', { name: 'New lab' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Import' })).toHaveCount(0)

  await page.context().close()
})

test('admin grants viewer access through the Access tab', async ({ page }) => {
  await page.goto(`/labs/${FAST_LAB}/access`)
  await expect(page.getByText('Owner: admin')).toBeVisible()
  await expect(page.getByText('No grants yet — the owner has full access.')).toBeVisible()

  const comboboxes = page.getByRole('combobox')
  await selectOption(page, comboboxes.nth(0), 'User')
  await selectOption(page, comboboxes.nth(1), VIEWER.username)
  await selectOption(page, comboboxes.nth(2), 'lab_viewer')
  await page.getByRole('button', { name: 'Grant', exact: true }).click()
  await expectToast(page, 'Access granted')
  const row = page.getByRole('row').filter({ hasText: VIEWER.username })
  await expect(row.getByText('lab_viewer', { exact: true })).toBeVisible()
  await expect(
    page.getByRole('button', { name: `Remove lab_viewer grant for ${VIEWER.username}` }),
  ).toBeVisible()
})

test('the granted lab shows read-only to the viewer', async ({ browser }) => {
  const page = await viewerPage(browser)

  await page.goto('/labs')
  await expect(page.getByRole('link', { name: FAST_LAB })).toBeVisible()
  // No destroy permission → no Actions column delete button.
  await expect(page.getByRole('button', { name: `Delete ${FAST_LAB}` })).toHaveCount(0)

  // The index redirect lands a pure reader on Overview; author tabs hidden.
  await page.goto(`/labs/${FAST_LAB}`)
  await page.waitForURL(`**/labs/${FAST_LAB}/overview`)
  const tabs = page.getByRole('navigation').last()
  await expect(tabs.getByRole('link', { name: 'Overview' })).toBeVisible()
  await expect(tabs.getByRole('link', { name: 'Build' })).toHaveCount(0)
  await expect(tabs.getByRole('link', { name: 'Access' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Deploy' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Configure' })).toHaveCount(0)

  // Deep links to gated tabs self-guard with honest copy.
  await page.goto(`/labs/${FAST_LAB}/build`)
  await expect(
    page.getByText("Editing this lab's definition requires the lab:edit permission."),
  ).toBeVisible()
  await page.goto(`/labs/${FAST_LAB}/access`)
  await expect(
    page.getByText('Managing access to this lab requires the grant permission.'),
  ).toBeVisible()

  await page.context().close()
})
