import { expect, test, type Page } from '@playwright/test'

import { connectNodes, flowEdges, flowNode, flowNodes } from '../../lib/canvas'
import { selectOption } from '../../lib/radix'
import { expectToast } from '../../lib/toast'

// The MPLS L3VPN walkthrough, executed. Every step the docs describe for
// building this lab in the VISUAL builder — lab defaults, the customer VRF,
// four PE and three P routers, all eleven links, the two config-template
// groups — in that order and nothing else. On VyOS, which is what the
// open-source tree supports; the docs' sibling walkthrough is the same
// topology on cisco_iol.
//
// It is therefore both the demo you can watch and the regression net for the
// builder: if a step here changes, the documented walkthrough is wrong.
//
// DEMO MODE — ONE continuous video of the whole story, slowed down enough to
// follow:
//
//   TWINLAB_DEMO=1 pnpm exec playwright test 11-builder-l3vpn --project=fast
//   scripts/demo-video.sh          # -> report/demo/walkthrough.webm
//
// The flag also collapses the five tests into one, because Playwright records
// one video per browser CONTEXT and a context is per test — as separate tests
// they came out as five disconnected clips. Each step keeps its name through
// `test.step`, so the trace still says where you are. Without the flag the
// spec runs at full speed as five tests and records nothing, so the suite
// stays fast and a failure still names the step it happened in.
test.describe.configure({ mode: 'serial' })

const DEMO = process.env['TWINLAB_DEMO'] === '1'
test.use({
  video: DEMO ? 'on' : 'off',
  // Playwright drives the UI faster than a person can read. Only the demo run
  // pays for the slowdown.
  launchOptions: DEMO ? { slowMo: 220 } : {},
})

const LAB = 'e2e-l3vpn'
const PES = ['pe1', 'pe2', 'pe3', 'pe4'] as const
const CORE = ['p1', 'p2', 'p3'] as const
// The walkthrough's link list, in its order: eight access links then three
// core links. Each is one `Connect to` + `Link` in the node inspector.
const ACCESS = [
  ['pe1', 'p1'],
  ['pe1', 'p2'],
  ['p1', 'pe2'],
  ['p3', 'pe2'],
  ['p2', 'pe3'],
  ['p3', 'pe3'],
  ['p2', 'pe4'],
  ['p3', 'pe4'],
] as const
const CORE_LINKS = [
  ['p1', 'p3'],
  ['p2', 'p3'],
  ['p1', 'p2'],
] as const

const canvas = (page: Page) => page.getByRole('region', { name: 'Topology builder canvas' })
const inspector = (page: Page) => page.locator('aside')

/** The lab inspector is what an empty selection shows, and a pane click is how
 * you deselect. LEFT-CENTRE is the reliably empty spot: the Add palette sits
 * top-left, the view tools top-right, React Flow's own controls bottom-left,
 * and dagre stacks the topology down the middle — so the centre column, and
 * the edges running through it, are exactly what to avoid. */
async function selectLab(page: Page) {
  const pane = canvas(page).locator('.react-flow__pane')
  const box = await pane.boundingBox()
  if (box === null) throw new Error('selectLab: the canvas is not visible')
  await pane.click({ position: { x: 40, y: box.height / 2 } })
  await expect(inspector(page).getByRole('tab', { name: 'Defaults' })).toBeVisible()
}

/** Rename the just-added node. It is auto-named from its device and already
 * selected. `from` is asserted rather than assumed — a selection that failed
 * to follow would otherwise rename the wrong node silently. */
async function rename(page: Page, from: string, to: string) {
  const field = inspector(page).getByLabel('Name', { exact: true })
  await expect(field).toHaveValue(from)
  await field.fill(to)
  await field.blur()
  await expect(flowNode(canvas(page), to)).toBeVisible()
}

async function createTheLab(page: Page) {
  await page.goto('/labs')

  // Start from nothing even on a re-run. A full suite run resets the stack in
  // globalSetup, but UI mode resets ONCE at startup and then re-runs on
  // demand — which is how this spec gets watched. The record count is the
  // barrier: count() is a ONE-SHOT, so asking it before the labs query
  // resolves reads zero rows and skips the delete, which is indistinguishable
  // from "the lab was not there".
  await expect(page.getByText(/^\d+ records?$/)).toBeVisible()
  const existing = page.getByRole('row').filter({ hasText: LAB })
  if ((await existing.count()) > 0) {
    await page.getByRole('button', { name: `Delete ${LAB}` }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click()
    await expectToast(page, `Deleted ${LAB}`)
    await expect(existing).toHaveCount(0)
  }

  await page.getByRole('button', { name: 'New lab' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name').fill(LAB)
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expectToast(page, `Lab ${LAB} created — author its definition, then deploy`)
  await page.waitForURL(`**/labs/${LAB}/overview`)
}

async function buildTheCore(page: Page) {
  await page.goto(`/labs/${LAB}/build`)
  const view = canvas(page)
  const aside = inspector(page)
  await expect(view).toBeVisible()

  // ---- 1. lab defaults ----------------------------------------------------
  await selectOption(page, aside.locator('#build-default-device'), 'VyOS')
  // Exact names: substring matching would let 'mpls' also hit the
  // 'LDP transport (mpls.ldp)' checkbox below.
  for (const module of ['ospf', 'mpls', 'bgp', 'vrf']) {
    await aside.getByRole('checkbox', { name: module, exact: true }).check()
  }
  await aside.getByLabel('BGP AS', { exact: true }).fill('65000')
  await aside.getByRole('checkbox', { name: 'LDP transport (mpls.ldp)' }).check()

  // ---- 2. declare the customer VPN ---------------------------------------
  // An empty body lets netlab derive the RD/RT from the VRF id.
  await aside.getByRole('tab', { name: /VRFs/ }).click()
  await aside.getByPlaceholder('vrf name').fill('vpn_a')
  await aside.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(aside.getByText('vpn_a', { exact: true })).toBeVisible()

  // ---- 3. the seven routers ----------------------------------------------
  // One click each: with a lab default set, the Add button's left half names
  // it and plants it. Every node inherits `defaults.device`.
  for (const name of [...PES, ...CORE]) {
    await page.getByRole('button', { name: 'Add VyOS', exact: true }).click()
    await rename(page, 'vyos1', name)
  }
  await expect(flowNodes(view)).toHaveCount(7)
  // Spread the pile: every add lands on the same spot, and a node stacked
  // under another (or behind the sticky header) is visible but unclickable.
  await page.getByRole('button', { name: 'Auto-layout' }).click()

  // ---- 4. the P routers are pure LSRs ------------------------------------
  // OSPF + LDP only: drop bgp and vrf from the inherited module set.
  for (const name of CORE) {
    await flowNode(view, name).click()
    await aside.getByRole('button', { name: 'Override for this node' }).click()
    for (const module of ['bgp', 'vrf']) {
      await aside.getByRole('checkbox', { name: module, exact: true }).uncheck()
    }
  }

  // ---- 5. the PEs are VPN edges, each holding a customer site -------------
  for (const name of PES) {
    await flowNode(view, name).click()
    await aside.getByRole('tab', { name: /Protocols/ }).click()
    await aside.getByRole('checkbox', { name: 'MPLS VPN edge (mpls.vpn)' }).check()
    await aside.getByRole('checkbox', { name: 'vpn_a', exact: true }).check()
    await aside.getByRole('checkbox', { name: 'customer loopback (the site)' }).check()
  }

  // ---- 6. the eleven links ------------------------------------------------
  // The first one by DRAG, so the canvas grip is exercised the way the
  // walkthrough describes it; the rest through the node inspector's target
  // picker, which is the same validateConnect verdict without the aiming.
  const [firstA, firstB] = ACCESS[0]
  await connectNodes(page, flowNode(view, firstA), flowNode(view, firstB))
  await expect(flowEdges(view)).toHaveCount(1)

  for (const [source, target] of [...ACCESS.slice(1), ...CORE_LINKS]) {
    await flowNode(view, source).click()
    await selectOption(page, aside.locator('#build-node-connect'), target)
    await aside.getByRole('button', { name: 'Link', exact: true }).click()
  }
  await expect(flowEdges(view)).toHaveCount(11)
  // Lay it out again now that it HAS a shape. The first auto-layout ran over
  // seven unconnected nodes, which dagre can only stack in a column; with the
  // links in place it draws the actual core-and-edge topology.
  await page.getByRole('button', { name: 'Auto-layout' }).click()

  // ---- 7. the two role groups ---------------------------------------------
  // Returning to the lab inspector is a click on empty canvas.
  await selectLab(page)
  await aside.getByRole('tab', { name: /Groups/ }).click()

  await aside.getByPlaceholder('group name').fill('pe')
  await aside.getByRole('button', { name: 'Add', exact: true }).click()
  for (const name of PES) {
    await aside.getByRole('checkbox', { name, exact: true }).check()
  }

  // The IOL walkthrough attaches Twinlab's built-in `mpls_te` and `ip_sla`
  // templates here — but they are IOS-only, and netlab would REJECT this
  // definition with "Cannot find mpls_te configuration template for
  // pe1/device vyos" if a vyos node carried them (proven: the save came back
  // as a netlab_invalid panel). Since delta 27 the picker KNOWS that: the
  // built-ins are offered greyed with the reason, so the mistake can no
  // longer be made. The VyOS build keeps the groups and leaves them
  // unattached; the scoping is what gets checked here.
  for (const template of ['mpls_te', 'ip_sla']) {
    const checkbox = aside.getByRole('checkbox', { name: template, exact: true })
    await expect(checkbox).toBeVisible()
    await expect(checkbox).toBeDisabled()
  }
  await expect(
    aside
      .locator('[title="No variant for member pe1 (vyos) — a group attaches to every member"]')
      .first(),
  ).toBeVisible()

  await aside.getByPlaceholder('group name').fill('core')
  await aside.getByRole('button', { name: 'Add', exact: true }).click()
  for (const name of CORE) {
    await aside.getByRole('checkbox', { name, exact: true }).check()
  }

  // ---- 8. save ------------------------------------------------------------
  // The server's dry `netlab create` is what judges the result.
  await aside.getByRole('button', { name: 'Save', exact: true }).click()
  await expectToast(page, `Definition saved. Deploy ${LAB} to apply it.`)
  await expect(page.getByText('unsaved changes')).toHaveCount(0)
}

// The editing affordances the walkthrough does not need but the builder
// carries. Kept apart so the walkthrough above stays exactly the documented
// sequence — and left in a state that does not disturb the saved lab.
async function editingAffordances(page: Page) {
  await page.goto(`/labs/${LAB}/build`)
  const view = canvas(page)
  const aside = inspector(page)
  await expect(flowNodes(view)).toHaveCount(7)

  // Duplicate carries the node's settings AND its group memberships.
  await flowNode(view, 'pe1').click()
  await aside.getByRole('button', { name: 'Duplicate' }).click()
  await expect(flowNodes(view)).toHaveCount(8)
  await aside.getByRole('tab', { name: /Protocols/ }).click()
  await expect(aside.getByRole('checkbox', { name: 'MPLS VPN edge (mpls.vpn)' })).toBeChecked()
  await expect(aside.getByRole('checkbox', { name: 'vpn_a', exact: true })).toBeChecked()

  // Copy/paste is the same path with a clipboard in between. The duplicate's
  // auto-name is read from the inspector rather than assumed — it comes from
  // the device and the first free index, which depends on what the lab holds.
  await aside.getByRole('tab', { name: /General/ }).click()
  const copied = await aside.getByLabel('Name', { exact: true }).inputValue()
  await aside.getByRole('button', { name: 'Copy', exact: true }).click()
  await expectToast(page, `Copied ${copied}`)
  await page.getByRole('button', { name: 'Paste node' }).click()
  await expect(flowNodes(view)).toHaveCount(9)

  // Undo walks both of them back out; redo puts one back.
  await page.keyboard.press('Control+z')
  await expect(flowNodes(view)).toHaveCount(8)
  await page.keyboard.press('Control+Shift+z')
  await expect(flowNodes(view)).toHaveCount(9)
  await page.getByRole('button', { name: 'Undo' }).click()
  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(flowNodes(view)).toHaveCount(7)

  // Back at the loaded definition, so nothing is unsaved — the derived dirty
  // flag is what makes that true rather than merely looking true.
  await expect(page.getByText('unsaved changes')).toHaveCount(0)
}

async function readBackTheDefinition(page: Page) {
  await page.goto(`/labs/${LAB}/build`)
  await page.getByRole('button', { name: 'Edit the definition as text' }).click()
  const editor = page.locator('.cm-editor')
  await expect(editor).toBeVisible()
  // .first(): a token can legitimately appear on several lines — `vpn_a:` is
  // both the top-level declaration and each PE's membership.
  for (const token of ['vpn_a:', 'pe1:']) {
    await expect(editor.getByText(token, { exact: true }).first()).toBeVisible()
  }
  // CodeMirror VIRTUALISES: only the lines near the viewport exist in the
  // DOM, so the tail of a definition this size has to be scrolled to before
  // it can be asserted at all.
  await page.locator('.cm-scroller').evaluate((el) => {
    el.scrollTop = el.scrollHeight
  })
  await expect(editor.getByText('- p1-p2', { exact: true }).first()).toBeVisible()
}

async function overviewRendersIt(page: Page) {
  await page.goto(`/labs/${LAB}/overview`)
  // The read-only canvas surfaces as `application` (React Flow overrides the
  // role prop), unlike the builder's `region` wrapper — see 05-builder-text.
  const view = page.getByRole('application', { name: 'Lab topology canvas' })
  await expect(view).toBeVisible()
  for (const node of [...PES, ...CORE]) {
    await expect(flowNode(view, node)).toBeVisible()
  }
  await expect(flowEdges(view)).toHaveCount(11)
}

// Normal runs keep the steps as separate tests: a failure names the step it
// happened in. A DEMO run stitches them into ONE test instead, because
// Playwright records one video per browser context and a context is per test
// — five tests would give five clips of the same story.
if (DEMO) {
  test('the walkthrough, end to end', async ({ page }) => {
    test.setTimeout(900_000)
    await test.step('create the lab', async () => {
      await createTheLab(page)
    })
    await test.step('build the L3VPN core, step by step, in the visual builder', async () => {
      await buildTheCore(page)
    })
    await test.step('editing affordances: duplicate, copy/paste, undo and redo', async () => {
      await editingAffordances(page)
    })
    await test.step('the saved definition reads back with everything the builder set', async () => {
      await readBackTheDefinition(page)
    })
    await test.step('the overview canvas renders the saved topology', async () => {
      await overviewRendersIt(page)
    })
  })
} else {
  test('create the lab', async ({ page }) => {
    await createTheLab(page)
  })
  test('build the L3VPN core, step by step, in the visual builder', async ({ page }) => {
    // Seven nodes and eleven links is a lot of UI for one default timeout.
    test.setTimeout(120_000)
    await buildTheCore(page)
  })
  test('editing affordances: duplicate, copy/paste, undo and redo', async ({ page }) => {
    await editingAffordances(page)
  })
  test('the saved definition reads back with everything the builder set', async ({ page }) => {
    await readBackTheDefinition(page)
  })
  test('the overview canvas renders the saved topology', async ({ page }) => {
    await overviewRendersIt(page)
  })
}
