import type { Locator } from '@playwright/test'

// Every YAML/JSON/Jinja surface in the app is CodeMirror 6 — a contenteditable
// .cm-content, not a form field, so fill() cannot drive it and auto-indent
// would mangle typed-in YAML. insertText dispatches one input event with the
// text verbatim, bypassing per-key handling.
//
// `editor` is any locator that contains the .cm-editor (a card, dialog, or the
// editor element itself).

export async function setEditorText(editor: Locator, text: string): Promise<void> {
  const content = editor.locator('.cm-content')
  await content.click()
  await content.press('ControlOrMeta+a')
  await content.press('Delete')
  await editor.page().keyboard.insertText(text)
}

// CodeMirror virtualizes long documents — only lines near the viewport exist
// in the DOM. Fine for the short documents the suite reads back; assertions on
// long ones should target visible fragments instead.
export async function editorText(editor: Locator): Promise<string> {
  const lines = await editor.locator('.cm-line').allTextContents()
  // CodeMirror renders an empty line as a zero-width-space-ish placeholder;
  // normalize non-breaking spaces so callers compare plain text.
  return lines.map((line) => line.replaceAll(' ', ' ')).join('\n')
}
