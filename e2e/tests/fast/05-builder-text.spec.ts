import { expect, test, type Page } from '@playwright/test'

import { E2E_NET_DEFINITION, FAST_LAB } from '../../fixtures/fixtures'
import { editorText, setEditorText } from '../../lib/editor'
import { flowNodes } from '../../lib/canvas'
import { expectToast } from '../../lib/toast'

// Text mode is the full-syntax escape hatch: this file replaces the visual
// draft with the real e2e-net fixture and pins the save-rejection surfaces.
test.describe.configure({ mode: 'serial' })

async function openTextMode(page: Page) {
  await page.goto(`/labs/${FAST_LAB}/build`)
  await page.getByRole('button', { name: 'Edit the definition as text' }).click()
  await expect(page.locator('.cm-editor')).toBeVisible()
}

test('the text editor lints, rejects loudly, and saves the e2e-net definition', async ({
  page,
}) => {
  await openTextMode(page)
  const editor = page.locator('.cm-editor')
  // The saved visual draft is the starting text.
  await expect(editor.getByText('r1:', { exact: true })).toBeVisible()

  // Broken YAML → a lint marker in the gutter (client-side; Save stays
  // available — the server's dry netlab create is the real validator).
  await setEditorText(editor, 'nodes: [r1\n')
  await expect(page.locator('.cm-lint-marker').first()).toBeVisible()
  await page.getByRole('button', { name: 'Reset' }).click()
  await expect(editor.getByText('r1:', { exact: true })).toBeVisible()

  // A legal-netlab key Twinlab rejects (tools:) → the 422 envelope's message
  // as an error toast.
  await setEditorText(editor, 'defaults.device: vyos\ntools:\n  graphite:\nnodes:\n  t1:\n')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expectToast(page, 'the definition uses netlab features Twinlab does not honor: tools')

  // A definition netlab itself rejects → the stderr panel, dismissable.
  await setEditorText(editor, 'defaults.device: nosuchdevice\nnodes:\n  t1:\n')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText(/netlab rejected the definition:/)).toBeVisible()
  await expect(page.locator('pre').first()).not.toBeEmpty()
  await page.getByRole('button', { name: 'Dismiss error' }).click()
  await expect(page.getByText(/netlab rejected the definition:/)).toHaveCount(0)

  // The real fixture saves clean.
  await setEditorText(editor, E2E_NET_DEFINITION)
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expectToast(page, `Definition saved. Deploy ${FAST_LAB} to apply it.`)
})

test('overview renders the saved definition: message card, canvas, text view', async ({
  page,
}) => {
  await page.goto(`/labs/${FAST_LAB}/overview`)

  // The definition's top-level message: feeds the About card.
  await expect(page.getByText('About this lab')).toBeVisible()
  await expect(
    page.getByText(/e2e-net — the Playwright journey's network\. An OSPF triangle/),
  ).toBeVisible()

  // Visual view: 5 devices + the services LAN hub; the stub is table-only.
  // Unlike the builder (a region wrapper), the read-only canvas surfaces as
  // the React Flow application node itself.
  const canvas = page.getByRole('application', { name: 'Lab topology canvas' })
  await expect(canvas).toBeVisible()
  await expect(flowNodes(canvas)).toHaveCount(6)

  // Text view shows the stored YAML read-only.
  await page.getByRole('tab', { name: 'Text' }).click()
  const editor = page.locator('.cm-editor')
  await expect(editor.getByText('defaults.device: vyos')).toBeVisible()
  // The PUT re-dumps the definition (name/subnet re-pinning), so the stored
  // text is normalized YAML: flow lists become block style.
  const text = await editorText(editor)
  expect(text).toContain('module:\n- ospf')

  // Details card: Nodes counts live CONTAINERS, so an authored-but-undeployed
  // lab still reads 0 — the definition alone deploys nothing.
  await expect(
    page.getByText('Nodes', { exact: true }).locator('xpath=following-sibling::div[1]'),
  ).toHaveText('0')
})
