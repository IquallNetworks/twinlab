import { expect, test } from '@playwright/test'

import { E2E_NET_NAME } from '../../fixtures/fixtures'

// On-demand validation and the facts viewer on the Tests tab, then the
// custom-config library on Operations — both against the live lab.
test.describe.configure({ mode: 'serial' })

test('the runtime suite runs green, and a result opens onto what it did', async ({ page }) => {
  test.setTimeout(240_000)
  await page.goto(`/labs/${E2E_NET_NAME}/tests`)

  // config-time sorts first, so reachability's Run is the second one.
  await page.getByRole('button', { name: 'Run', exact: true }).nth(1).click()
  await expect(page.getByRole('button', { name: 'Running…' })).toBeVisible()
  // Run all is disabled meanwhile — the per-lab job mutex would refuse it —
  // but it did not start this run and must not claim to be it.
  await expect(page.getByRole('button', { name: 'Run all' })).toBeDisabled()

  // Two loopback pings (r1→r3, r3→r1), both green — folded onto the test that
  // produced them rather than listed as two unrelated rows.
  const ping = page.getByTestId('test-reachability-loopback_ping')
  const tally = ping.getByRole('button', { name: '2 passed' })
  await expect(tally).toBeVisible({ timeout: 180_000 })

  // A pill is the node's verdict; clicking it opens the result. An all-passing
  // run folds its pills away first, since a row of identical verdicts is not
  // what anyone came to read.
  await tally.click()
  await ping.getByRole('button', { name: 'r1', exact: true }).click()
  await expect(ping.getByText(/ping -c 3 -W 2 10\.\d+\.\d+\.\d+/)).toBeVisible()
  await expect(ping.getByText('Output', { exact: true })).toBeVisible()
  // The <pre>, not just any text: the detail line quotes the expectation
  // verbatim, so a bare text match finds "expected to contain '3 packets…'"
  // as well as the output that satisfied it.
  await expect(ping.locator('pre', { hasText: '3 packets transmitted' })).toBeVisible()
})

test('Try runs an unsaved case against the live lab', async ({ page }) => {
  // Delta 31's loop-closer, against a real node: the Try button POSTs the case
  // being edited and shows what it did — the point being that nothing is saved
  // first, and the PARSED structure comes back, which is what makes the
  // compare below it writable.
  test.setTimeout(120_000)
  await page.goto(`/labs/${E2E_NET_NAME}/tests`)

  // The device-keyed json case: parse is already json, so the probe returns a
  // structure and not just text.
  await page
    .getByTestId('test-convergence-ospf_peers_json')
    .getByRole('button', { name: 'Edit' })
    .click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('Parse output as')).toContainText('JSON')

  await dialog.getByRole('button', { name: 'Try', exact: true }).click()
  // The ADAPTED command: VyOS op-mode reached through the wrapper, which is
  // what actually ran — not what was typed.
  await expect(dialog.getByText(/vyatta-op-cmd-wrapper|vtysh/)).toBeVisible({ timeout: 60_000 })
  await expect(dialog.getByText('Output', { exact: true })).toBeVisible()
  await expect(dialog.getByText(/write the .*compare.* against this/)).toBeVisible()

  // It stored nothing — the suite's last run is still whatever it was.
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(page.getByText('convergence', { exact: true })).toBeVisible()
})

test('the facts viewer serves the node namespace', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/tests`)
  await page.getByRole('button', { name: 'Facts' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('Node facts')).toBeVisible()
  // The fact JSON is long and CodeMirror virtualizes — assert on the promised
  // core keys near the TOP of the first node's dict, which are always in the
  // rendered viewport.
  await expect(dialog.locator('.cm-editor').getByText('"mgmt"').first()).toBeVisible({
    timeout: 30_000,
  })
  await page.keyboard.press('Escape')
})

test('custom config lists the built-in template tier', async ({ page }) => {
  await page.goto(`/labs/${E2E_NET_NAME}/operations`)
  const card = page.locator('[data-slot="card"]', { hasText: 'Custom config' }).first()
  await expect(card.locator('[data-slot="badge"]', { hasText: 'built-in' }).first()).toBeVisible()
  await expect(card.getByText('mpls_te')).toBeVisible()
  await expect(card.getByText('ip_sla')).toBeVisible()
})
