import { expect, test, type Page } from '@playwright/test'

import { FAST_LAB } from '../../fixtures/fixtures'
import { connectNodes, dragNodeBy, flowEdges, flowNode } from '../../lib/canvas'
import { expectToast } from '../../lib/toast'

// The Build tab's visual mode on the fast-tier lab. One serial story: the
// canvas starts blank, gains nodes/links through palette + drag, saves, then
// exercises the emit blocker and both unsaved-changes guards.
test.describe.configure({ mode: 'serial' })

const canvas = (page: Page) => page.getByRole('region', { name: 'Topology builder canvas' })
const inspector = (page: Page) => page.locator('aside')

async function openBuild(page: Page) {
  await page.goto(`/labs/${FAST_LAB}/build`)
  await expect(canvas(page)).toBeVisible()
}

test('blank canvas teaches, the Add menu lists the catalog', async ({ page }) => {
  await openBuild(page)
  await expect(page.getByText('blank canvas')).toBeVisible()
  await expect(page.getByText('a device from the menu, drag between nodes to connect them')).toBeVisible()

  await page.getByRole('button', { name: 'Add', exact: true }).click()
  for (const device of ['VyOS', 'FRRouting', 'MikroTik RouterOS 7 (CHR)', 'BIRD routing daemon', 'dnsmasq DHCP/DNS server', 'Linux host']) {
    await expect(page.getByRole('menuitem', { name: device })).toBeVisible()
  }
  await expect(
    page.getByRole('menuitem', { name: "Node templates appear here — save one from a node's General tab" }),
  ).toBeDisabled()
  await expect(page.getByRole('menuitem', { name: 'LAN segment' })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: 'From config file…' })).toBeVisible()
  await page.keyboard.press('Escape')
})

test('palette adds, inspector renames and enables OSPF, drag connects, save persists', async ({
  page,
}) => {
  await openBuild(page)

  // Nothing selected yet → the aside is the LAB inspector: enable OSPF as a
  // global module on the Defaults tab.
  const aside = inspector(page)
  await expect(aside.getByRole('tab', { name: 'Defaults' })).toBeVisible()
  await aside.getByRole('checkbox', { name: 'ospf' }).check()
  await expect(page.getByText('unsaved changes')).toBeVisible()

  // Two devices from the palette; auto-named <device><n>. New nodes spawn
  // stacked on one default spot and every ADD re-runs auto-placement, so
  // spread them only after the last add. While stacked, pointer events land
  // on the first-added node — dragging vyos1 off the pile is deterministic.
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await page.getByRole('menuitem', { name: 'VyOS' }).click()
  await expect(flowNode(canvas(page), 'vyos1')).toBeVisible()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await page.getByRole('menuitem', { name: 'FRRouting' }).click()
  await expect(flowNode(canvas(page), 'frr1')).toBeVisible()
  await dragNodeBy(page, flowNode(canvas(page), 'vyos1'), -240, -80)

  // Drag-to-connect the two nodes; the edge appears.
  await connectNodes(page, flowNode(canvas(page), 'vyos1'), flowNode(canvas(page), 'frr1'))
  await expect(flowEdges(canvas(page))).toHaveCount(1)

  // Rename vyos1 → r1: the node inspector's General tab. The reducer keeps
  // the link's endpoint in step — the edge survives the rename. (The module
  // section defers to the global default set above.)
  await flowNode(canvas(page), 'vyos1').click()
  await expect(aside.getByLabel('Name', { exact: true })).toHaveValue('vyos1')
  await expect(aside.getByText(/Inherits global modules/)).toBeVisible()
  await expect(aside.getByRole('button', { name: 'Override for this node' })).toBeVisible()
  await aside.getByLabel('Name', { exact: true }).fill('r1')
  await aside.getByLabel('Name', { exact: true }).blur()
  await expect(flowNode(canvas(page), 'r1')).toBeVisible()
  await expect(flowEdges(canvas(page))).toHaveCount(1)

  // Name the link through the link inspector.
  await flowEdges(canvas(page)).first().click({ force: true })
  await expect(aside.getByText('r1 ↔ frr1')).toBeVisible()
  await aside.getByLabel('Name', { exact: true }).fill('core')
  await aside.getByLabel('Name', { exact: true }).blur()

  await aside.getByRole('button', { name: 'Save', exact: true }).click()
  await expectToast(page, `Definition saved. Deploy ${FAST_LAB} to apply it.`)
  await expect(page.getByText('unsaved changes')).toHaveCount(0)
})

test('a 2-member LAN blocks save loudly and Discard recovers', async ({ page }) => {
  await openBuild(page)
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await page.getByRole('menuitem', { name: 'LAN segment' }).click()
  const lan = canvas(page).locator('.react-flow__node[data-id^="lan"]').first()
  await dragNodeBy(page, lan, -60, 200)
  await connectNodes(page, flowNode(canvas(page), 'r1'), lan)
  await connectNodes(page, flowNode(canvas(page), 'frr1'), lan)

  await expect(page.getByText('Not saveable yet:')).toBeVisible()
  await expect(inspector(page).getByRole('button', { name: 'Save', exact: true })).toBeDisabled()

  await page.getByRole('button', { name: 'Discard' }).click()
  await expect(page.getByText('Not saveable yet:')).toHaveCount(0)
  await expect(page.getByText('unsaved changes')).toHaveCount(0)
})

test('mode switch and route leave both guard unsaved changes', async ({ page }) => {
  await openBuild(page)
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Linux host' }).click()
  await expect(page.getByText('unsaved changes')).toBeVisible()

  // Switching to text mode with a dirty draft asks first; Stay keeps it.
  await page.getByRole('button', { name: 'Edit the definition as text' }).click()
  await expect(page.getByText('Discard unsaved changes?')).toBeVisible()
  await page.getByRole('button', { name: 'Stay' }).click()
  await expect(flowNode(canvas(page), 'linux1')).toBeVisible()

  // Leaving the route with a dirty draft asks too.
  await page.getByRole('navigation').getByRole('link', { name: 'Labs', exact: true }).click()
  await expect(page.getByText('Leave with unsaved changes?')).toBeVisible()
  await expect(page.getByText('The definition changes you made here are not saved.')).toBeVisible()
  await page.getByRole('button', { name: 'Stay' }).click()
  await expect(canvas(page)).toBeVisible()

  // Discard-and-switch drops the draft: the text editor shows the SAVED copy.
  await page.getByRole('button', { name: 'Edit the definition as text' }).click()
  await page.getByRole('button', { name: 'Discard and switch' }).click()
  const editor = page.locator('.cm-editor')
  await expect(editor).toBeVisible()
  await expect(editor.getByText('r1:', { exact: true })).toBeVisible()
  await expect(editor.getByText('linux1')).toHaveCount(0)
})
