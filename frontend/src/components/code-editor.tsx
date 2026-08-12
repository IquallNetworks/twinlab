import {
  autocompletion,
  closeBrackets,
  closeBracketsKeymap,
  completionKeymap,
  type CompletionSource,
} from '@codemirror/autocomplete'
import { indentWithTab } from '@codemirror/commands'
import { json, jsonParseLinter } from '@codemirror/lang-json'
import { yaml } from '@codemirror/lang-yaml'
import {
  HighlightStyle,
  StreamLanguage,
  bracketMatching,
  indentOnInput,
  indentUnit,
  syntaxHighlighting,
} from '@codemirror/language'
import { jinja2 } from '@codemirror/legacy-modes/mode/jinja2'
import { linter, lintGutter } from '@codemirror/lint'
import { Compartment, EditorState, type Extension } from '@codemirror/state'
import {
  EditorView,
  keymap,
  lineNumbers,
  placeholder as cmPlaceholder,
  tooltips,
} from '@codemirror/view'
import { tags } from '@lezer/highlight'
import { minimalSetup } from 'codemirror'
import { useEffect, useRef } from 'react'
import { parseDocument } from 'yaml'

import { cn } from '@/lib/utils'

export type CodeLanguage = 'yaml' | 'jinja2' | 'json'

/* Colors come from the theme tokens (styles/theme.css) so the editor tracks
 * dark/light switches live, with no JS re-render. */
const editorTheme = EditorView.theme({
  '&': {
    /* The container className owns sizing: a definite height flows in via
     * height:100%; min-h/max-h containers flow in via inherit (height:100%
     * resolves to auto there, so the editor content-sizes within the cap
     * and the scroller scrolls). */
    height: '100%',
    minHeight: 'inherit',
    maxHeight: 'inherit',
    backgroundColor: 'var(--card)',
    color: 'var(--foreground)',
  },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': {
    fontFamily: 'var(--font-mono)',
    lineHeight: '1.6',
    overflow: 'auto',
  },
  '.cm-content': { caretColor: 'var(--foreground)', padding: '8px 0' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--foreground)' },
  /* drawSelection paints the selection itself, so with these set the editor
   * needs no dark-mode flag at all. */
  '.cm-selectionBackground, &.cm-focused .cm-selectionBackground': {
    backgroundColor: 'color-mix(in oklab, var(--primary) 25%, transparent)',
  },
  '.cm-content ::selection': {
    backgroundColor: 'color-mix(in oklab, var(--primary) 25%, transparent)',
  },
  '.cm-gutters': {
    backgroundColor: 'var(--muted)',
    color: 'var(--muted-foreground)',
    borderRight: '1px solid var(--border)',
  },
  '.cm-placeholder': { color: 'var(--muted-foreground)' },
  '.cm-tooltip': {
    backgroundColor: 'var(--popover)',
    color: 'var(--popover-foreground)',
    border: '1px solid var(--border)',
    borderRadius: '2px',
    fontFamily: 'var(--font-sans)',
    /* The host CodeMirror creates for an external tooltip parent is
     * `pointer-events: none`, and the tooltip inherits it — so a completion
     * list rendered outside the editor is visible but unclickable. */
    pointerEvents: 'auto',
  },
  '.cm-diagnostic-error': { borderLeftColor: 'var(--destructive)' },
  '.cm-lintRange-error': {
    backgroundImage: 'none',
    textDecoration: 'underline wavy var(--destructive) 1px',
    textUnderlineOffset: '3px',
  },
})

const highlight = HighlightStyle.define([
  { tag: [tags.propertyName, tags.definition(tags.propertyName), tags.meta], color: 'var(--id-code-key)' },
  { tag: tags.string, color: 'var(--foreground)' },
  {
    tag: [tags.number, tags.bool, tags.atom, tags.null, tags.keyword],
    color: 'var(--id-code-literal)',
  },
  { tag: tags.comment, color: 'var(--id-code-comment)', fontStyle: 'italic' },
])

/* yaml's parseDocument collects every error without throwing; each carries
 * character offsets — exactly CodeMirror's Diagnostic shape. prettyErrors is
 * off so messages stay one-line (no embedded source excerpt). */
const yamlLinter = linter((view) => {
  const text = view.state.doc.toString()
  if (text.trim() === '') return []
  return parseDocument(text, { prettyErrors: false }).errors.map((error) => ({
    from: Math.min(error.pos[0], text.length),
    to: Math.min(Math.max(error.pos[1], error.pos[0] + 1), text.length),
    severity: 'error' as const,
    message: error.message,
  }))
})

function languageExtension(language: CodeLanguage): Extension {
  switch (language) {
    case 'yaml':
      return yaml()
    case 'json':
      return json()
    case 'jinja2':
      return StreamLanguage.define(jinja2)
  }
}

/* jinja2 has no linter — the option is simply inert there. */
function lintExtension(language: CodeLanguage): Extension {
  switch (language) {
    case 'yaml':
      return [lintGutter(), yamlLinter]
    case 'json':
      return [lintGutter(), linter(jsonParseLinter())]
    case 'jinja2':
      return []
  }
}

function readOnlyExtension(readOnly: boolean): Extension {
  return readOnly ? [EditorState.readOnly.of(true), EditorView.editable.of(false)] : []
}

/** CodeMirror 6 as a controlled component. Sizing belongs to `className`
 * (height / min-h / max-h); readOnly defaults to "no onChange given". */
export function CodeEditor({
  value,
  onChange,
  language,
  readOnly,
  placeholder,
  autoFocus = false,
  lint = false,
  gutter = true,
  completions,
  className,
}: {
  value: string
  onChange?: (text: string) => void
  language: CodeLanguage
  readOnly?: boolean
  placeholder?: string
  autoFocus?: boolean
  lint?: boolean
  /** Line numbers. Off for a one-line field, where the gutter is noise. */
  gutter?: boolean
  /** Completion source, e.g. the lab's fact namespace. Routed through a ref so
   * a source that closes over changing data (the target node's facts) stays
   * current without reconfiguring the editor. */
  completions?: CompletionSource
  className?: string
}) {
  const effectiveReadOnly = readOnly ?? onChange === undefined

  const containerRef = useRef<HTMLDivElement | null>(null)
  const viewRef = useRef<EditorView | null>(null)
  const compartments = useRef({
    language: new Compartment(),
    lint: new Compartment(),
    readOnly: new Compartment(),
    placeholder: new Compartment(),
  })
  /* The listener extension lives for the view's whole life; routing through a
   * ref keeps it current without reconfiguring. */
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange
  const completionsRef = useRef(completions)
  completionsRef.current = completions
  const mountConfig = useRef({
    value,
    language,
    lint,
    readOnly: effectiveReadOnly,
    placeholder,
    autoFocus,
    gutter,
  })
  mountConfig.current = {
    value,
    language,
    lint,
    readOnly: effectiveReadOnly,
    placeholder,
    autoFocus,
    gutter,
  }

  useEffect(() => {
    const parent = containerRef.current
    if (parent === null) return
    const init = mountConfig.current
    const c = compartments.current
    const view = new EditorView({
      parent,
      state: EditorState.create({
        doc: init.value,
        extensions: [
          /* Before minimalSetup so closeBracketsKeymap wins over the default
           * Backspace binding. */
          keymap.of([...closeBracketsKeymap, indentWithTab]),
          keymap.of(completionKeymap),
          minimalSetup,
          ...(init.gutter ? [lineNumbers()] : []),
          autocompletion({
            override: [
              (context) => completionsRef.current?.(context) ?? null,
            ],
          }),
          /* A tooltip is absolutely positioned INSIDE the editor, so every
           * ancestor that clips clips it: this component's own rounded
           * `overflow-hidden` wrapper first, then whatever scrolls around it.
           * The completion list came out as a sliver at the bottom edge of a
           * one-line field, which reads as being painted behind the form.
           * Parenting to the body takes it out of the clipping chain
           * entirely — and CodeMirror's z-index (500) clears the dialog's. */
          tooltips({ parent: document.body }),
          bracketMatching(),
          closeBrackets(),
          indentOnInput(),
          indentUnit.of('  '),
          editorTheme,
          syntaxHighlighting(highlight),
          c.language.of(languageExtension(init.language)),
          c.lint.of(init.lint ? lintExtension(init.language) : []),
          c.readOnly.of(readOnlyExtension(init.readOnly)),
          c.placeholder.of(init.placeholder !== undefined ? cmPlaceholder(init.placeholder) : []),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) onChangeRef.current?.(update.state.doc.toString())
          }),
        ],
      }),
    })
    viewRef.current = view
    if (init.autoFocus) view.focus()
    return () => {
      view.destroy()
      viewRef.current = null
    }
  }, [])

  /* External value changes (reset, server re-seed). A change that originated
   * from typing round-trips as an equal string and is skipped, so the caret
   * never jumps. */
  useEffect(() => {
    const view = viewRef.current
    if (view === null) return
    const current = view.state.doc.toString()
    if (value !== current) {
      view.dispatch({ changes: { from: 0, to: current.length, insert: value } })
    }
  }, [value])

  useEffect(() => {
    viewRef.current?.dispatch({
      effects: [
        compartments.current.language.reconfigure(languageExtension(language)),
        compartments.current.lint.reconfigure(lint ? lintExtension(language) : []),
      ],
    })
  }, [language, lint])

  useEffect(() => {
    viewRef.current?.dispatch({
      effects: compartments.current.readOnly.reconfigure(readOnlyExtension(effectiveReadOnly)),
    })
  }, [effectiveReadOnly])

  useEffect(() => {
    viewRef.current?.dispatch({
      effects: compartments.current.placeholder.reconfigure(
        placeholder !== undefined ? cmPlaceholder(placeholder) : [],
      ),
    })
  }, [placeholder])

  return (
    <div
      ref={containerRef}
      className={cn(
        'overflow-hidden rounded-[2px] border bg-card text-xs transition-colors',
        !effectiveReadOnly &&
          'focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50',
        className,
      )}
    />
  )
}
