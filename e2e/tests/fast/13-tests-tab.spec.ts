import { expect, test, type Locator, type Page } from '@playwright/test'

import { FAST_LAB } from '../../fixtures/fixtures'
import { editorText, setEditorText } from '../../lib/editor'
import { expectToast } from '../../lib/toast'

// The Tests tab and its editors. Authoring is a PUT against the lab record, so
// this needs no containers — which is why it is a fast spec. Try and Run are
// the parts that need a live node, and journey 04 drives those.
//
// The lab is FAST_LAB, built in 04/05: a VyOS core with linux hosts and a
// `core` group, so its devices DISAGREE on capability and there is a real
// group to target — both of which the assertions below depend on.

test.describe.configure({ mode: 'serial' })

/** The command field is a one-line CodeMirror, and a `compare` assertion adds
 * a second editor — so always take the first. */
function commandEditor(dialog: Locator): Locator {
  return dialog.locator('.cm-editor').first()
}

/** Open the edit dialog for one test, from its card on the tab. */
async function editTest(page: Page, suite: string, name: string): Promise<Locator> {
  await page.getByTestId(`test-${suite}-${name}`).getByRole('button', { name: 'Edit' }).click()
  return page.getByRole('dialog')
}

test('a suite is created, then its first test is written', async ({ page }) => {
  await page.goto(`/labs/${FAST_LAB}/tests`)

  // Start from nothing even on a re-run — UI mode and E2E_SKIP_RESET replay
  // this spec on the state a previous run left (the 11-builder precedent).
  // Once "Loading…" is gone the body is settled, so the one-shot isVisible
  // below cannot race the suites query; if suites exist, the JSON escape
  // hatch clears the whole map in one save.
  await expect(page.getByText('Loading…')).toBeHidden()
  const empty = page.getByText('No test suites yet.')
  if (!(await empty.isVisible())) {
    await page.getByRole('button', { name: 'JSON' }).click()
    const json = page.getByRole('dialog')
    await setEditorText(json.locator('.cm-editor'), '{}')
    await json.getByRole('button', { name: 'Save' }).click()
    await expectToast(page, 'Saved test suites')
  }
  await expect(empty).toBeVisible()

  // A suite is a container: name, stage, description, and nothing else. The
  // work is in the tests, which is why creating one is this small.
  await page.getByRole('button', { name: 'Create the first suite' }).click()
  const create = page.getByRole('dialog')
  await create.getByLabel('Name').fill('e2e-smoke')
  await create.getByLabel('Description').fill('the fast lab still answers')

  // Creating hands straight to the test editor and saves NOTHING yet: a blank
  // test has no command, and the API rightly refuses one — so there is no
  // half-made suite to leave behind.
  await create.getByRole('button', { name: 'Next: the first test' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'e2e-smoke · check' })).toBeVisible()

  await dialog.getByLabel('Test name').fill('loopback_up')
  await dialog.getByLabel('Description').fill('the loopback is up')

  // Delta 32: a new test targets EVERY node — the edit-proof default, so a
  // node added to the lab later is tested without anyone remembering to.
  await expect(dialog.getByLabel('Runs on')).toContainText('Every node in the lab')
  await expect(dialog.getByText('Stays correct as the lab grows')).toBeVisible()

  // A command is required, so an unfinished test cannot reach the API at all.
  await expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled()

  await setEditorText(commandEditor(dialog), 'ip -o link show lo')
  await dialog.getByLabel('Expected value').fill('UP')
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expectToast(page, 'Saved test suites')

  // The suite and its first test arrive together.
  const suite = page.locator('[data-slot="card"]', { hasText: 'e2e-smoke' }).first()
  await expect(suite.getByText('Never run.')).toBeVisible()

  // The card carries what the test IS — its target and its command — without
  // opening anything. That is the point of the tab.
  const card = page.getByTestId('test-e2e-smoke-loopback_up')
  await expect(card).toBeVisible()
  await expect(card.getByText('the loopback is up')).toBeVisible()
  await expect(card.getByText('ip -o link show lo')).toBeVisible()
  await expect(card.locator('[data-slot="badge"]', { hasText: 'every node' })).toBeVisible()
  await expect(card.getByText('No results — run the suite to see what this does.')).toBeVisible()
})

test('the summary and the filters read the run state of the whole lab', async ({ page }) => {
  await page.goto(`/labs/${FAST_LAB}/tests`)
  await expect(page.getByText('1 suite · 1 test')).toBeVisible()
  await expect(page.getByText('Nothing has run yet.')).toBeVisible()

  // Nothing has run, so "problems" is empty and "not run" is everything. A
  // suite contributing nothing to the filter shrinks to one line rather than
  // rendering its whole header to say so.
  await page.getByRole('tab', { name: 'Problems' }).click()
  await expect(page.getByText('1 test, none matching this filter')).toBeVisible()
  await expect(page.getByTestId('test-e2e-smoke-loopback_up')).toBeHidden()
  // The count chip in the summary is the same filter, from the other side.
  await page.getByRole('button', { name: '1 suite never run' }).click()
  await expect(page.getByTestId('test-e2e-smoke-loopback_up')).toBeVisible()
  await page.getByRole('tab', { name: 'All tests' }).click()
})

test('the target composes a group with named nodes', async ({ page }) => {
  await page.goto(`/labs/${FAST_LAB}/tests`)
  const dialog = await editTest(page, 'e2e-smoke', 'loopback_up')

  await dialog.getByLabel('Runs on').click()
  await page.getByRole('option', { name: 'Selected groups and nodes' }).click()

  // The lab's own group, resolved server-side to its members.
  await dialog.getByRole('checkbox', { name: 'core' }).check()
  await expect(dialog.getByText(/Runs on r1, r2, r3/)).toBeVisible()

  // A node the group already covers cannot be unticked here — it is selected
  // by the group, and pretending otherwise would be a lie.
  await expect(dialog.getByRole('checkbox', { name: 'r1' })).toBeDisabled()

  // …and a node outside it composes on top: "the group, plus h1".
  await dialog.getByRole('checkbox', { name: 'h1' }).check()
  await expect(dialog.getByText(/Runs on r1, r2, r3, h1/)).toBeVisible()

  // Deselecting everything is refused, because a test that targets nothing
  // silently never runs.
  await dialog.getByRole('checkbox', { name: 'core' }).uncheck()
  await dialog.getByRole('checkbox', { name: 'h1' }).uncheck()
  await expect(dialog.getByText(/must target something/)).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled()

  await dialog.getByRole('button', { name: 'Cancel' }).click()
})

test('the command field completes the lab fact namespace', async ({ page }) => {
  await page.goto(`/labs/${FAST_LAB}/tests`)
  const dialog = await editTest(page, 'e2e-smoke', 'loopback_up')

  const content = commandEditor(dialog).locator('.cm-content')
  await content.click()
  await content.press('ControlOrMeta+a')
  await content.press('Delete')
  // Typed key by key: completion is driven by input events, not by a paste.
  await page.keyboard.type('ping {{ node.')
  // The promised core of the namespace, offered from what the lab actually has.
  const popup = page.locator('.cm-tooltip-autocomplete')
  await expect(popup).toBeVisible()
  await expect(page.locator('.cm-completionLabel', { hasText: 'loopback' })).toBeVisible()

  // And it is not CLIPPED to the one-line field. A CodeMirror tooltip is
  // absolutely positioned inside the editor, so the rounded `overflow-hidden`
  // wrapper used to cut the list down to a sliver that read as being painted
  // behind the form; it is parented to the body now. Visibility alone does not
  // catch that — the box has to reach past the field it belongs to.
  const field = await commandEditor(dialog).boundingBox()
  const list = await popup.boundingBox()
  expect(field).not.toBeNull()
  expect(list).not.toBeNull()
  expect(list!.y + list!.height).toBeGreaterThan(field!.y + field!.height)

  // Pick it the way a user does. A container applies with its dot, because
  // the level below is the point of picking it.
  await page.locator('.cm-completionLabel', { hasText: 'loopback' }).first().click()
  await expect
    .poll(() => editorText(commandEditor(dialog)))
    .toContain('ping {{ node.loopback.')

  await dialog.getByRole('button', { name: 'Cancel' }).click()
})

test('the test dialog survives a stray click outside it', async ({ page }) => {
  await page.goto(`/labs/${FAST_LAB}/tests`)
  const dialog = await editTest(page, 'e2e-smoke', 'loopback_up')
  await expect(dialog).toBeVisible()

  // A test in progress is real work; discarding it on a misclick is not on.
  await page.mouse.click(5, 5)
  await expect(dialog).toBeVisible()

  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toBeHidden()
})

test('cli mode is offered only where the device has a CLI', async ({ page }) => {
  await page.goto(`/labs/${FAST_LAB}/tests`)
  const dialog = await editTest(page, 'e2e-smoke', 'loopback_up')

  // The saved test targets every node, and the lab has linux hosts, so CLI
  // mode is unavailable — correctly: their shell IS the interface.
  await expect(dialog.getByText(/has no CLI of its own/)).toBeVisible()
  await dialog.getByLabel('Command language').click()
  await expect(page.getByRole('option', { name: /CLI/ })).toBeDisabled()
  await page.keyboard.press('Escape')

  // Narrow to the VyOS routers and it becomes a real choice.
  await dialog.getByLabel('Runs on').click()
  await page.getByRole('option', { name: 'Selected groups and nodes' }).click()
  await dialog.getByRole('checkbox', { name: 'core' }).check()
  await expect(dialog.getByText(/has no CLI of its own/)).toBeHidden()
  await dialog.getByLabel('Command language').click()
  await expect(page.getByRole('option', { name: /CLI/ })).toBeEnabled()
  await page.keyboard.press('Escape')

  await dialog.getByRole('button', { name: 'Cancel' }).click()
})

test('the JSON view is the whole set, and is still the escape hatch', async ({ page }) => {
  await page.goto(`/labs/${FAST_LAB}/tests`)
  await page.getByRole('button', { name: 'JSON' }).click()
  const dialog = page.getByRole('dialog')

  // Lossless both ways because the suite schema is CLOSED — what the visual
  // editors wrote is here verbatim, `all_nodes` included.
  const json = dialog.locator('.cm-editor')
  await expect(json.getByText('e2e-smoke')).toBeVisible()
  await expect(json.getByText('loopback_up')).toBeVisible()
  await expect(json.getByText('all_nodes')).toBeVisible()

  await dialog.getByRole('button', { name: 'Cancel' }).click()
})

test('a test duplicates, and deleting one asks first', async ({ page }) => {
  await page.goto(`/labs/${FAST_LAB}/tests`)
  const card = page.getByTestId('test-e2e-smoke-loopback_up')
  await card.getByRole('button', { name: 'More actions for loopback_up' }).click()
  await page.getByRole('menuitem', { name: 'Duplicate' }).click()
  await expectToast(page, 'Saved test suites')

  const copy = page.getByTestId('test-e2e-smoke-loopback_up-copy')
  await expect(copy).toBeVisible()

  // Authored suites are not versioned, so a delete is confirmed.
  await copy.getByRole('button', { name: 'More actions for loopback_up-copy' }).click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()
  await expect(page.getByText('Delete test loopback_up-copy?')).toBeVisible()
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await expectToast(page, 'Saved test suites')
  await expect(copy).toBeHidden()
})
