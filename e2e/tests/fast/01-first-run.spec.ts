import { expect, test, type Page } from '@playwright/test'

import { stackEnv } from '../../lib/env'

const env = stackEnv()

// The pristine-backend assertions: this file must run before anything in the
// suite creates data (file order + one worker guarantees it).

function statValue(page: Page, label: string) {
  // A stat tile is the one div whose DIRECT child span is the label; the
  // second span carries the value.
  return page.locator(`div:has(> span:text-is("${label}"))`).locator('span').nth(1)
}

test('dashboard opens on fleet zeros, teaching empty states and admin counts', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page).toHaveTitle('Twinlab — Dashboard')
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  await expect(page.getByRole('main').getByText(env.adminUsername, { exact: true })).toBeVisible()

  await expect(statValue(page, 'labs')).toHaveText('0')
  await expect(statValue(page, 'deployed')).toHaveText('0')
  await expect(statValue(page, 'nodes running')).toHaveText('0/0')
  await expect(statValue(page, 'config-time failures')).toHaveText('0')

  // Labs board: the teaching empty state for a caller who can create.
  await expect(page.getByText('no labs yet')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Create your first lab' })).toBeVisible()
  await expect(page.getByText(', author its netlab definition, then deploy.')).toBeVisible()
  await expect(page.getByRole('link', { name: 'New lab' })).toBeVisible()

  // Recent operations: the shared jobs-table empty state.
  await expect(page.getByText('no operations')).toBeVisible()
  await expect(page.getByText('Deploy, configure and validation runs appear here.')).toBeVisible()

  // Activity: session-scoped SSE feed, necessarily empty on a fresh session.
  await expect(page.getByText('no activity yet')).toBeVisible()
  await expect(
    page.getByText('Live lab events appear here as they happen this session.'),
  ).toBeVisible()

  // Administration: exactly the bootstrap admin, no groups.
  await expect(page.getByText('Administration')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Users 1' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Groups 0' })).toBeVisible()
})

test('labs page opens empty with the create/import affordances', async ({ page }) => {
  await page.goto('/labs')
  await expect(page).toHaveTitle('Twinlab — Labs')
  await expect(page.getByRole('heading', { name: 'Labs' })).toBeVisible()
  await expect(page.getByText('0 records')).toBeVisible()
  await expect(page.getByText('no lab records')).toBeVisible()
  await expect(page.getByText('Create one, author its netlab definition, then deploy.')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Import' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'New lab' })).toBeVisible()
  for (const header of ['Name', 'Status', 'Owner', 'Nodes', 'Created']) {
    await expect(page.getByRole('columnheader', { name: header })).toBeVisible()
  }
})

test('jobs center opens empty with the status filter', async ({ page }) => {
  await page.goto('/jobs')
  await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible()
  await expect(page.getByText('0 jobs')).toBeVisible()
  await expect(page.getByText('no operations')).toBeVisible()
  await expect(page.getByText('Deploy, configure and validation runs appear here.')).toBeVisible()
  await expect(page.getByRole('combobox')).toBeVisible()
})

test('shell chrome: nav, active link, footer, theme toggle', async ({ page }) => {
  await page.goto('/labs')
  const nav = page.getByRole('navigation')
  for (const link of ['Dashboard', 'Labs', 'Jobs', 'Users', 'Groups', 'Account']) {
    await expect(nav.getByRole('link', { name: link, exact: true })).toBeVisible()
  }
  await expect(nav.getByRole('link', { name: 'Labs', exact: true })).toHaveAttribute(
    'data-status',
    'active',
  )
  await expect(nav.getByRole('link', { name: 'Dashboard', exact: true })).not.toHaveAttribute(
    'data-status',
    'active',
  )

  await expect(page.getByText('Twinlab — network twin laboratory')).toBeVisible()
  await expect(page.getByText('declarative · reproducible')).toBeVisible()

  // The toggle names the theme it would switch TO; clicking flips both the
  // label and the html class.
  const toggle = page.getByRole('button', { name: /Switch to (light|dark) theme/ })
  const before = await toggle.getAttribute('aria-label')
  const goingLight = before === 'Switch to light theme'
  await toggle.click()
  await expect(
    page.getByRole('button', {
      name: goingLight ? 'Switch to dark theme' : 'Switch to light theme',
    }),
  ).toBeVisible()
  const html = page.locator('html')
  if (goingLight) {
    await expect(html).not.toHaveClass(/dark/)
  } else {
    await expect(html).toHaveClass(/dark/)
  }
  await toggle.click()
})

test('unknown routes and labs land on honest not-found pages', async ({ page }) => {
  await page.goto('/no-such-page')
  await expect(page.getByText('404 — no such page')).toBeVisible()
  await expect(page.getByText('Nothing lives at this address.')).toBeVisible()
  await page.getByRole('link', { name: 'Back to dashboard' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

  await page.goto('/labs/e2e-ghost')
  await expect(page.getByText('No lab named e2e-ghost.')).toBeVisible()
})

test('styleguide renders as the dev-only gallery', async ({ page }) => {
  await page.goto('/styleguide')
  await expect(page.getByRole('heading', { name: 'Styleguide' })).toBeVisible()
  await expect(page.getByText('Identity under review:')).toBeVisible()
})
