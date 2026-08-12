import { expect, test } from '@playwright/test'

import { E2E_NET_DEFINITION, E2E_NET_NAME, E2E_NET_SUITES } from '../../fixtures/fixtures'
import { setEditorText } from '../../lib/editor'
import { expectToast } from '../../lib/toast'

// The journey opens: create e2e-net, author it, attach its suites, deploy
// WITH config push, and watch the job through every surface that reports it.
test.describe.configure({ mode: 'serial' })

test('create and author the journey lab', async ({ page }) => {
  await page.goto('/labs')
  await page.getByRole('button', { name: 'New lab' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name').fill(E2E_NET_NAME)
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expectToast(page, `Lab ${E2E_NET_NAME} created — author its definition, then deploy`)
  await page.waitForURL(`**/labs/${E2E_NET_NAME}/overview`)

  await page.goto(`/labs/${E2E_NET_NAME}/build`)
  await page.getByRole('button', { name: 'Edit the definition as text' }).click()
  const editor = page.locator('.cm-editor')
  await expect(editor).toBeVisible()
  await setEditorText(editor, E2E_NET_DEFINITION)
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expectToast(page, `Definition saved. Deploy ${E2E_NET_NAME} to apply it.`)
})

test('attach the test suites; runs are gated on a running lab', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/tests`)
  await expect(page.getByText('No test suites yet.')).toBeVisible()

  // Pasting a whole suite set is what the JSON escape hatch is for; the
  // visual path authors one test at a time (fast/13 drives that side).
  await page.getByRole('button', { name: 'JSON' }).click()
  const dialog = page.getByRole('dialog')
  await setEditorText(dialog.locator('.cm-editor'), E2E_NET_SUITES)
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expectToast(page, 'Saved test suites')

  // Both suites list with stage badges, and every test shows what it targets
  // and what it runs without opening anything.
  await expect(page.getByText('convergence', { exact: true })).toBeVisible()
  await expect(page.getByText('reachability', { exact: true })).toBeVisible()
  await expect(page.locator('[data-slot="badge"]', { hasText: 'config-time' })).toBeVisible()
  await expect(page.getByText('Never run.')).toHaveCount(2)
  await expect(page.getByTestId('test-convergence-ospf_adjacency')).toBeVisible()
  await expect(page.getByTestId('test-reachability-loopback_ping')).toBeVisible()

  const run = page.getByRole('button', { name: 'Run', exact: true }).first()
  await expect(run).toBeDisabled()
  await expect(run).toHaveAttribute('title', 'Run is available while the lab is running')
})

test('deploy with config push, watched from jobs, dashboard and the header', async ({ page }) => {
  // Deploy + configure + config-time gate on five nodes: minutes, not seconds.
  test.setTimeout(900_000)

  await page.goto(`/labs/${E2E_NET_NAME}/overview`)
  await page.getByRole('button', { name: 'Deploy', exact: true }).click()
  await expect(page.getByText(`Deploy ${E2E_NET_NAME}?`)).toBeVisible()
  await page.getByLabel('Push configuration after deploy (adds minutes)').check()
  await page.getByRole('dialog').getByRole('button', { name: 'Deploy', exact: true }).click()

  // The lab is now mid-flight everywhere. The lifecycle badge is the FIRST
  // badge in main (beside the h1) — hasText filters elsewhere have matched
  // unrelated badges and let the suite race ahead of the running job.
  const statusBadge = page.getByRole('main').locator('[data-slot="badge"]').first()
  await expect(statusBadge).toHaveText(/deploying/)
  await page.goto('/jobs')
  // Job rows are keyboard-focusable buttons, not plain table rows; their
  // accessible name is "<kind> <status>, open details".
  const runningRow = page.getByRole('button', { name: 'deploy running, open details' })
  await expect(runningRow.first()).toBeVisible()
  await runningRow.first().click()
  const sheet = page.locator('[data-slot="sheet-content"]')
  await expect(sheet.getByText(E2E_NET_NAME)).toBeVisible()
  await expect(sheet.getByText('request', { exact: true })).toBeVisible()
  await expect(sheet.getByText('"configure": true')).toBeVisible()
  // The step log (contract delta 29): the drawer says what the operation is
  // DOING, not just that it is running. Which phase is on screen depends on
  // how far the deploy has got, so assert on the first one — it is recorded
  // seconds in and never disappears.
  await expect(sheet.getByText('steps', { exact: true })).toBeVisible()
  await expect(sheet.getByText('topology_generated')).toBeVisible({ timeout: 120_000 })
  await page.keyboard.press('Escape')

  // The dashboard's session-scoped activity feed fills from the SSE stream as
  // containers come up.
  await page.goto('/')
  const activity = page.locator('[data-slot="card"]', { hasText: 'Activity' })
  await expect(activity.getByRole('link', { name: E2E_NET_NAME }).first()).toBeVisible({
    timeout: 300_000,
  })

  // The lifecycle badge flips to deployed when the CONTAINERS are up, but the
  // job keeps configuring past that — the Last-operation badge reaching
  // `succeeded` is the true deploy+configure+gate barrier (a suite run
  // submitted before it would 409 on the per-lab job mutex).
  await page.goto(`/labs/${E2E_NET_NAME}/overview`)
  await expect(page.getByRole('main').locator('[data-slot="badge"]').first()).toHaveText(
    /deployed$/,
    { timeout: 300_000 },
  )
  await expect(page.getByText('Last operation:')).toBeVisible({ timeout: 60_000 })
  await expect(page.locator('[data-slot="badge"]', { hasText: 'succeeded' })).toBeVisible({
    timeout: 600_000,
  })

  // The config-time gate ran green: 3 adjacency results + 1 compare. The
  // Tests tab folds those onto the tests that produced them — one row of
  // per-node pills each, rather than four undifferentiated rows.
  await page.goto(`/labs/${E2E_NET_NAME}/tests`)
  const convergence = page.locator('[data-slot="card"]', { hasText: 'convergence' }).first()
  await expect(convergence.locator('[data-slot="badge"]', { hasText: 'passing' })).toBeVisible()
  await expect(convergence.getByText('4 passed')).toBeVisible()
  const adjacency = page.getByTestId('test-convergence-ospf_adjacency')
  // A run where every node passed folds its pills behind the tally — there is
  // nothing to point at — so the nodes are one click away, not on the page.
  await adjacency.getByRole('button', { name: '3 passed' }).click()
  for (const node of ['r1', 'r2', 'r3']) {
    await expect(adjacency.getByRole('button', { name: node, exact: true })).toBeVisible()
  }
})
