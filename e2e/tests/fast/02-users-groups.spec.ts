import { expect, test } from '@playwright/test'

import { VIEWER } from '../../fixtures/fixtures'
import { expectToast } from '../../lib/toast'

test('create the limited user through the Users page', async ({ page, browser }) => {
  await page.goto('/users')
  await expect(page).toHaveTitle('Twinlab — Users')
  await expect(page.getByRole('heading', { name: 'Users' })).toBeVisible()
  await expect(page.getByText('1 account', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'New user' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('New user')).toBeVisible()

  // The zod floors surface before anything is sent: the server's structural
  // email rule, and the password floor (an EMPTY password is allowed — the
  // server generates one — but a short one is not).
  await dialog.getByLabel('Username').fill(VIEWER.username)
  await dialog.getByLabel('Display name').fill(VIEWER.displayName)
  await dialog.getByLabel('Email').fill('not-an-address')
  await dialog.getByLabel('Password', { exact: true }).fill('short')
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expect(dialog.getByText('Enter an email address, like ana@example.com')).toBeVisible()
  await expect(dialog.getByText('Password must be at least 8 characters')).toBeVisible()

  await dialog.getByLabel('Email').fill(VIEWER.email)

  await dialog.getByLabel('Password', { exact: true }).fill(VIEWER.password)
  await dialog.getByRole('checkbox', { name: 'user', exact: true }).check()
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expectToast(page, `Created user ${VIEWER.username}`)

  // The table now carries both accounts with their role and status badges,
  // the person shown by display name and email.
  await expect(page.getByText('2 accounts', { exact: true })).toBeVisible()
  const viewerRow = page.getByRole('row').filter({ hasText: VIEWER.username })
  await expect(viewerRow.getByText(VIEWER.displayName)).toBeVisible()
  await expect(viewerRow.getByText(VIEWER.email)).toBeVisible()
  await expect(viewerRow.getByText('user', { exact: true })).toBeVisible()
  await expect(viewerRow.getByText('active', { exact: true })).toBeVisible()
  const adminRow = page.getByRole('row').filter({ hasText: /^admin/ })
  await expect(adminRow.getByText('admin', { exact: true }).nth(1)).toBeVisible()

  // Edit roles: the dialog names its subject.
  await viewerRow.getByRole('button', { name: 'Edit roles' }).click()
  await expect(page.getByText(`Roles for ${VIEWER.username}`)).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()

  // Administrative reset: no current password asked for. Set a throwaway,
  // prove the viewer can sign in with it, then put the fixture password back —
  // 09 signs in with that one.
  const throwaway = 'e2e-viewer-throwaway'
  await viewerRow.getByRole('button', { name: 'Reset password' }).click()
  await expect(dialog.getByText(`Reset password for ${VIEWER.username}`)).toBeVisible()
  await dialog.getByLabel('New password', { exact: true }).fill(throwaway)
  await dialog.getByLabel('Confirm new password').fill('something else')
  await dialog.getByRole('button', { name: 'Reset password' }).click()
  await expect(dialog.getByText('Passwords do not match')).toBeVisible()
  await dialog.getByLabel('Confirm new password').fill(throwaway)
  await dialog.getByRole('button', { name: 'Reset password' }).click()
  await expectToast(page, `Password reset for ${VIEWER.username}`)

  const viewerContext = await browser.newContext()
  const viewerPage = await viewerContext.newPage()
  await viewerPage.goto('/login')
  await viewerPage.getByLabel('Username').fill(VIEWER.username)
  await viewerPage.getByLabel('Password', { exact: true }).fill(throwaway)
  await viewerPage.getByRole('button', { name: 'Sign in' }).click()
  await expect(viewerPage.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  await viewerContext.close()

  await viewerRow.getByRole('button', { name: 'Reset password' }).click()
  await dialog.getByLabel('New password', { exact: true }).fill(VIEWER.password)
  await dialog.getByLabel('Confirm new password').fill(VIEWER.password)
  await dialog.getByRole('button', { name: 'Reset password' }).click()
  await expectToast(page, `Password reset for ${VIEWER.username}`)

  // Deactivation is the reversible half of delete, and the status badge follows.
  await viewerRow.getByRole('button', { name: 'Deactivate' }).click()
  const confirm = page.getByRole('alertdialog')
  await expect(confirm.getByText(`Deactivate ${VIEWER.username}?`)).toBeVisible()
  await confirm.getByRole('button', { name: 'Deactivate' }).click()
  await expectToast(page, `Deactivated ${VIEWER.username}`)
  await expect(viewerRow.getByText('inactive', { exact: true })).toBeVisible()

  // Reactivating needs no confirmation — it restores what deactivating suspended.
  await viewerRow.getByRole('button', { name: 'Activate' }).click()
  await expectToast(page, `Activated ${VIEWER.username}`)
  await expect(viewerRow.getByText('active', { exact: true })).toBeVisible()

  // Delete, on a throwaway account nothing later in the suite needs — created
  // with the password left EMPTY, so the server generates one and the dialog
  // shows it exactly once.
  await page.getByRole('button', { name: 'New user' }).click()
  await dialog.getByLabel('Username').fill('e2e-temp')
  await dialog.getByLabel('Display name').fill('E2E Temp')
  await dialog.getByLabel('Email').fill('e2e-temp@e2e.test')
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expectToast(page, 'Created user e2e-temp')
  await expect(dialog.getByText('Created e2e-temp')).toBeVisible()
  await expect(dialog.getByText('It is shown only once')).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Copy password' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByText('3 accounts', { exact: true })).toBeVisible()

  // The profile edits in place; an email already in use is refused.
  const tempRow = page.getByRole('row').filter({ hasText: 'e2e-temp' })
  await tempRow.getByRole('button', { name: 'Profile' }).click()
  await expect(dialog.getByText('Profile of e2e-temp')).toBeVisible()
  await dialog.getByLabel('Email').fill(VIEWER.email.toUpperCase())
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText(`an account already uses ${VIEWER.email.toUpperCase()}`)).toBeVisible()
  await dialog.getByLabel('Email').fill('e2e-temp-renamed@e2e.test')
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expectToast(page, 'Updated profile of e2e-temp')
  await expect(tempRow.getByText('e2e-temp-renamed@e2e.test')).toBeVisible()

  await tempRow.getByRole('button', { name: 'Delete' }).click()
  await expect(confirm.getByText('Delete e2e-temp?')).toBeVisible()
  await confirm.getByRole('button', { name: 'Delete' }).click()
  await expectToast(page, 'Deleted user e2e-temp')
  await expect(page.getByText('2 accounts', { exact: true })).toBeVisible()

  // Never on your own row: all three would act on the session making the request.
  await expect(adminRow.getByRole('button', { name: 'Reset password' })).toBeDisabled()
  await expect(adminRow.getByRole('button', { name: 'Deactivate' })).toBeDisabled()
  await expect(adminRow.getByRole('button', { name: 'Delete' })).toBeDisabled()
  await expect(adminRow.getByRole('button', { name: 'Delete' })).toHaveAttribute(
    'title',
    'You cannot delete the account you are signed in as',
  )

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
