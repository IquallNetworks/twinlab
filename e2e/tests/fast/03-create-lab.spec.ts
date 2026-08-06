import { expect, test } from '@playwright/test'

import { FAST_LAB } from '../../fixtures/fixtures'
import { expectToast } from '../../lib/toast'

test('create-lab dialog validates and creates the fast-tier lab', async ({ page }) => {
  await page.goto('/labs')
  await page.getByRole('button', { name: 'New lab' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('New lab')).toBeVisible()
  await expect(
    dialog.getByText(
      'Name the lab. You author its netlab definition and deploy it from the lab page — the name is its durable identity.',
    ),
  ).toBeVisible()

  // Client-side validation mirrors the server's name rule, which is netlab's
  // id rule: the name is pinned into the definition as the topology `name:`,
  // so anything wider would create a lab whose definition PUT can never pass.
  const hint = 'Start with a letter; then letters, digits, dash or underscore'
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expect(dialog.getByText('A lab name is required')).toBeVisible()
  await dialog.getByLabel('Name').fill('bad name!')
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expect(dialog.getByText(hint)).toBeVisible()
  await dialog.getByLabel('Name').fill('dotted.name')
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expect(dialog.getByText(hint)).toBeVisible()
  await dialog.getByLabel('Name').fill('seventeen-chars-x')
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expect(dialog.getByText('At most 16 characters')).toBeVisible()

  await dialog.getByLabel('Name').fill(FAST_LAB)
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expectToast(page, `Lab ${FAST_LAB} created — author its definition, then deploy`)

  // The index route redirects an author to Overview.
  await page.waitForURL(`**/labs/${FAST_LAB}/overview`)
  await expect(page.getByRole('heading', { name: FAST_LAB })).toBeVisible()
  await expect(page.locator('[data-slot="badge"]', { hasText: 'created' })).toBeVisible()

  // Getting-started teaching card + the definition empty state.
  await expect(page.getByText('Getting started')).toBeVisible()
  await expect(page.getByText('Author the topology on the')).toBeVisible()
  await expect(page.getByText('Deploy from the controls above (config push optional).')).toBeVisible()
  await expect(page.getByText('Connect to the running nodes from the Nodes tab.')).toBeVisible()
  await expect(page.getByText('No definition yet — build one on the')).toBeVisible()

  // Details card facts.
  await expect(page.getByText('Owner').locator('xpath=following-sibling::div[1]')).toHaveText('admin')
  await expect(page.getByText('Nodes', { exact: true }).locator('xpath=following-sibling::div[1]')).toHaveText('0')
})

test('the lab lists with its record row', async ({ page }) => {
  await page.goto('/labs')
  await expect(page.getByText('1 record', { exact: true })).toBeVisible()
  const row = page.getByRole('row').filter({ hasText: FAST_LAB })
  await expect(row.getByRole('link', { name: FAST_LAB })).toBeVisible()
  await expect(row.locator('[data-slot="badge"]', { hasText: 'created' })).toBeVisible()
  await expect(row.getByText('admin', { exact: true })).toBeVisible()
  await expect(row.getByText('0/0')).toBeVisible()
})

test('command palette opens the create dialog via ?new=1', async ({ page }) => {
  await page.goto('/')
  // The header button opens it too (the Ctrl+K shortcut is 10's business —
  // right after a cold load the window listener may not be mounted yet).
  await page.getByRole('button', { name: 'Command palette' }).click()
  const palette = page.getByRole('dialog')
  await expect(palette.getByPlaceholder('Go to a page or lab…')).toBeVisible()
  await palette.getByPlaceholder('Go to a page or lab…').fill('create')
  await palette.getByRole('option', { name: 'Create lab' }).click()
  // TanStack Router serializes {new: true} as ?new=true (validateSearch
  // accepts both spellings).
  await page.waitForURL(
    (url) => url.pathname === '/labs' && url.searchParams.get('new') !== null,
  )
  await expect(page.getByRole('dialog').getByText('New lab')).toBeVisible()
  // Closing clears the search param.
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()
  await page.waitForURL((url) => url.pathname === '/labs' && url.search === '')
})

test('a lab record can be deleted from its row', async ({ page }) => {
  await page.goto('/labs')
  await page.getByRole('button', { name: 'New lab' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name').fill('e2e-doomed')
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expectToast(page, 'Lab e2e-doomed created — author its definition, then deploy')
  await page.waitForURL('**/labs/e2e-doomed/overview')

  await page.goto('/labs')
  await expect(page.getByText('2 records', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Delete e2e-doomed' }).click()
  await expect(page.getByText('Delete e2e-doomed?')).toBeVisible()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click()
  // Deletion waits on an async job server-side; the toast lands when it ends.
  await expectToast(page, 'Deleted e2e-doomed')
  await expect(page.getByText('1 record', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'e2e-doomed' })).toHaveCount(0)
})
