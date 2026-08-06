import { expect, test } from '@playwright/test'

import { IMPORT_R1_CONFIG, IMPORT_R2_CONFIG } from '../../fixtures/fixtures'
import { flowNode } from '../../lib/canvas'
import { selectOption } from '../../lib/radix'
import { expectToast } from '../../lib/toast'

// The three-step import wizard on the two VyOS fixtures: sources → wiring
// (explicit, delta 23 — prefilled from the server's suggestion) → review →
// create, landing on the Build tab with the inferred twin.
test('the import wizard turns two VyOS configs into a lab', async ({ page }) => {
  await page.goto('/labs/import')
  await expect(page.getByRole('heading', { name: 'Import from config files' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Back to labs' })).toBeVisible()

  // Step 1 — sources: device + pasted config per row.
  await selectOption(page, page.getByRole('combobox').first(), 'VyOS')
  await page.getByLabel('Source config').fill(IMPORT_R1_CONFIG)
  await page.getByRole('button', { name: 'Add source' }).click()
  await selectOption(page, page.getByRole('combobox').nth(1), 'VyOS')
  await page.getByLabel('Source config').nth(1).fill(IMPORT_R2_CONFIG)
  await page.getByRole('button', { name: 'Next: wiring' }).click()

  // Step 2 — wiring: the shared /30 is proposed as one p2p entry. Hyphenated
  // hostnames are legal netlab identifiers, so imp-r1 keeps its name all the
  // way through — the review step's rename line stays away. ("Wiring entry"
  // the textbox, not the "Remove wiring entry" button getByLabel also matches.)
  await expect(page.getByRole('heading', { name: 'Wiring' })).toBeVisible()
  const entry = page.getByRole('textbox', { name: 'Wiring entry' })
  await expect(entry).toHaveValue(/imp-r1:eth1.*imp-r2:eth1|imp-r2:eth1.*imp-r1:eth1/)
  await expect(page.locator('[data-slot="badge"]', { hasText: 'p2p' })).toBeVisible()
  await page.getByRole('button', { name: 'Analyze' }).click()

  // Step 3 — review: warnings, renames, definition, per-node maps, carry,
  // quarantine (the ssh service lines class as `authentication`).
  await expect(page.getByText('1 warning', { exact: true })).toBeVisible()
  await expect(
    page.getByText(
      /imp-r1: interface eth2 \(10\.220\.1\.1\/24\) is not wired to a peer; realized as a stub/,
    ),
  ).toBeVisible()
  await expect(page.getByText(/Renamed for netlab/)).toHaveCount(0)
  await expect(page.getByText('Inferred definition')).toBeVisible()
  await expect(page.locator('.cm-editor').getByText('imp-r1:', { exact: true })).toBeVisible()
  // The unwired eth2 realizes as a dummy; loopback pins land on dum0.
  await expect(page.getByText('eth2 → dum1')).toBeVisible()
  await expect(page.getByText('lo → dum0').first()).toBeVisible()
  await page.getByRole('button', { name: 'Show carried config' }).first().click()
  await expect(page.getByText(/protocols static route/).first()).toBeVisible()
  await expect(
    page.getByText('Quarantined (kept, not applied — attach from Custom config later)').first(),
  ).toBeVisible()
  await expect(page.getByText('authentication', { exact: true }).first()).toBeVisible()

  // Create: compose create → custom config → definition, land on Build.
  await page.getByLabel('Lab name').fill('e2e-imported')
  await page.getByRole('button', { name: 'Create lab' }).click()
  await expectToast(page, 'Imported into e2e-imported')
  await page.waitForURL('**/labs/e2e-imported/build')
  const canvas = page.getByRole('region', { name: 'Topology builder canvas' })
  await expect(flowNode(canvas, 'imp-r1')).toBeVisible()
  await expect(flowNode(canvas, 'imp-r2')).toBeVisible()
})
