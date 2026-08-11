import { expect, test } from '@playwright/test'

// Host resources (delta 30). These describe the MACHINE, not any lab, so they
// render the same on a pristine backend as on a busy one — which is exactly
// why they belong in the fast project.

test('the dashboard reports what the host is spending', async ({ page }) => {
  await page.goto('/')
  const host = page.locator('[data-slot="card"]', {
    has: page.locator('[data-slot="card-title"]', { hasText: /^Host$/ }),
  })

  // Each measure is a labelled meter, so a reading that stops arriving is
  // visible as a missing bar rather than a silent zero.
  await expect(page.getByRole('meter', { name: 'cpu' })).toBeVisible()
  await expect(page.getByRole('meter', { name: 'memory' })).toBeVisible()
  // The compose stack requires LAB_FILES_DIR, so its filesystem is measured.
  await expect(page.getByRole('meter', { name: /^\// })).toBeVisible()

  await expect(host.getByText(/\d+% of \d+ cores/)).toBeVisible()
  await expect(host.getByText(/available of/)).toBeVisible()
  await expect(host.getByText(/^load /)).toBeVisible()
})

test('the dashboard reports what the container daemon holds on disk', async ({ page }) => {
  await page.goto('/')
  const storage = page.locator('[data-slot="card"]', {
    has: page.locator('[data-slot="card-title"]', { hasText: /^Storage$/ }),
  })

  for (const header of ['Holding', 'In use', 'Size', 'Reclaimable']) {
    await expect(storage.getByRole('columnheader', { name: header })).toBeVisible()
  }
  // The four kinds `docker system df` reports, in the operator's words.
  for (const kind of ['Node & service images', 'Container layers', 'Volumes', 'Build cache']) {
    await expect(storage.getByRole('cell', { name: kind })).toBeVisible()
  }
  // The stack running this test is itself containers on that daemon.
  await expect(storage.getByText(/\d+ of \d+ containers running/)).toBeVisible()
})
