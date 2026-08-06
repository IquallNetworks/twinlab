import { expect, test } from '@playwright/test'

import { VIEWER } from '../../fixtures/fixtures'
import { expectToast } from '../../lib/toast'

test('create the limited user through the Users page', async ({ page }) => {
  await page.goto('/users')
  await expect(page).toHaveTitle('Twinlab — Users')
  await expect(page.getByRole('heading', { name: 'Users' })).toBeVisible()
  await expect(page.getByText('1 account', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'New user' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('New user')).toBeVisible()

  // The zod floor surfaces before anything is sent.
  await dialog.getByLabel('Username').fill(VIEWER.username)
  await dialog.getByLabel('Password', { exact: true }).fill('short')
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expect(dialog.getByText('Password must be at least 8 characters')).toBeVisible()

  await dialog.getByLabel('Password', { exact: true }).fill(VIEWER.password)
  await dialog.getByRole('checkbox', { name: 'user', exact: true }).check()
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expectToast(page, `Created user ${VIEWER.username}`)

  // The table now carries both accounts with their role and status badges.
  await expect(page.getByText('2 accounts', { exact: true })).toBeVisible()
  const viewerRow = page.getByRole('row').filter({ hasText: VIEWER.username })
  await expect(viewerRow.getByText('user', { exact: true })).toBeVisible()
  await expect(viewerRow.getByText('active', { exact: true })).toBeVisible()
  const adminRow = page.getByRole('row').filter({ hasText: /^admin/ })
  await expect(adminRow.getByText('admin', { exact: true }).nth(1)).toBeVisible()

  // Edit roles: the dialog names its subject.
  await viewerRow.getByRole('button', { name: 'Edit roles' }).click()
  await expect(page.getByText(`Roles for ${VIEWER.username}`)).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()

  // The dashboard admin card follows.
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'Users 2' })).toBeVisible()
})

test('group lifecycle: create, members, roles, delete', async ({ page }) => {
  await page.goto('/groups')
  await expect(page).toHaveTitle('Twinlab — Groups')
  await expect(page.getByText('0 groups', { exact: true })).toBeVisible()
  await expect(page.getByText('no groups')).toBeVisible()

  await page.getByRole('button', { name: 'New group' }).click()
  let dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name').fill('e2e-team')
  await dialog.getByLabel('Description').fill('the suite’s scratch group')
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expectToast(page, 'Created group e2e-team')
  await expect(page.getByText('1 group', { exact: true })).toBeVisible()

  const row = page.getByRole('row').filter({ hasText: 'e2e-team' })
  await expect(row.getByText('the suite’s scratch group')).toBeVisible()

  // Members: pick both accounts, the cell lists them.
  await row.getByRole('button', { name: 'Members' }).click()
  dialog = page.getByRole('dialog')
  await expect(dialog.getByText('Members of e2e-team')).toBeVisible()
  await dialog.getByRole('checkbox', { name: 'admin', exact: true }).check()
  await dialog.getByRole('checkbox', { name: VIEWER.username }).check()
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expectToast(page, 'Updated members of e2e-team')
  await expect(row.getByText(`admin, ${VIEWER.username}`)).toBeVisible()

  // Roles dialog: title + inheritance copy.
  await row.getByRole('button', { name: 'Roles' }).click()
  dialog = page.getByRole('dialog')
  await expect(dialog.getByText('Global roles for e2e-team')).toBeVisible()
  await expect(dialog.getByText('Roles every member inherits, on every lab.')).toBeVisible()
  await dialog.getByRole('button', { name: 'Cancel' }).click()

  // Delete: confirm dialog explains the blast radius.
  await row.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByText('Delete e2e-team?')).toBeVisible()
  await expect(
    page.getByText('This removes the group and every grant made to it. Members keep their own grants.'),
  ).toBeVisible()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click()
  await expectToast(page, 'Deleted group e2e-team')
  await expect(page.getByText('0 groups', { exact: true })).toBeVisible()
})
