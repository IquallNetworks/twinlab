import { Info } from 'lucide-react'
import { useState } from 'react'
import { parse, stringify } from 'yaml'

import { CodeEditor } from '@/components/code-editor'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import type { Extras } from '@/lib/build-doc'
import { cn } from '@/lib/utils'

// The advanced-properties editor: the lossless-passthrough half of the
// builder. Whatever the typed controls don't model is edited here as a YAML
// mapping, preserved verbatim in the doc's extras. Validation is the shared
// shape classifier: a key the typed controls own (in its exact editable
// shape) is refused with a pointer to the control — the same rule
// parseBuildDoc splits on, so a key can never live in both places.

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

const PRESERVED_NOTE =
  'Preserved verbatim in the definition — the server’s dry netlab run still validates the content on save.'

export function ExtrasEditor({
  idPrefix,
  value,
  keyError,
  onApply,
  label = 'Advanced properties',
  placeholder = 'any netlab keys the controls don’t cover, e.g.\nvlans:\n  red:\n    id: 100',
  bare = false,
}: {
  idPrefix: string
  value: Extras | undefined
  // The level's classifier (labExtrasKeyError / nodeExtrasKeyError / …).
  keyError: (key: string, value: unknown) => string | null
  // Receives the parsed mapping; undefined = cleared (empty text).
  onApply: (extras: Extras | undefined) => void
  // Summary text — override where several editors sit in one panel (a link's
  // per-endpoint sections).
  label?: string
  placeholder?: string
  // bare = no collapsible wrapper — for panels that already provide one (the
  // node inspector's merged Advanced section) so collapsibles never nest.
  bare?: boolean
}) {
  const baseline = value !== undefined && Object.keys(value).length > 0 ? stringify(value) : ''
  const [text, setText] = useState(baseline)
  const [errors, setErrors] = useState<string[]>([])
  const dirty = text !== baseline
  const count = value !== undefined ? Object.keys(value).length : 0

  const apply = () => {
    if (text.trim() === '') {
      setErrors([])
      onApply(undefined)
      return
    }
    let parsed: unknown
    try {
      parsed = parse(text)
    } catch (err) {
      setErrors([`not valid YAML: ${err instanceof Error ? err.message : String(err)}`])
      return
    }
    if (!isRecord(parsed)) {
      setErrors(['advanced properties must be a YAML mapping'])
      return
    }
    const found: string[] = []
    for (const [key, entry] of Object.entries(parsed)) {
      const error = keyError(key, entry)
      if (error !== null) found.push(`"${key}": ${error}`)
    }
    if (found.length > 0) {
      setErrors(found)
      return
    }
    setErrors([])
    onApply(parsed)
  }

  const body = (
    <div className={cn('flex flex-col gap-1.5', !bare && 'mt-2')}>
      <Label htmlFor={`${idPrefix}-extras`} className={bare ? undefined : 'sr-only'}>
        {label}
      </Label>
      <CodeEditor
        value={text}
        onChange={(next) => setText(next)}
        language="yaml"
        placeholder={placeholder}
        className="max-h-48 min-h-16 rounded-[2px] border"
      />
      {errors.length > 0 && (
        <ul className="list-inside list-disc text-xs text-destructive">
          {errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" disabled={!dirty} onClick={apply}>
          Apply
        </Button>
        {dirty && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setText(baseline)
              setErrors([])
            }}
          >
            Reset
          </Button>
        )}
        <span className="ml-auto text-muted-foreground" title={PRESERVED_NOTE}>
          <Info className="size-3.5" aria-hidden="true" />
          <span className="sr-only">{PRESERVED_NOTE}</span>
        </span>
      </div>
    </div>
  )

  if (bare) return body

  return (
    <details>
      <summary className="cursor-pointer text-xs text-muted-foreground select-none">
        {label}
        {count > 0 ? ` (${count})` : ''}
      </summary>
      {body}
    </details>
  )
}
