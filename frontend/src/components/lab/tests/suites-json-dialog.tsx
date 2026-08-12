import { useState } from 'react'
import { toast } from 'sonner'

import { CodeEditor } from '@/components/code-editor'
import type { Suites } from '@/components/lab/tests/use-save-suites'
import { useSaveSuites } from '@/components/lab/tests/use-save-suites'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { testSuiteSchema } from '@/lib/schemas'

/** Read a suite map out of the JSON view. The wire schema is the authority —
 * what is saved here must be exactly what a GET would hand back, or the visual
 * editors would be handed a shape they never validated. */
export function parseSuiteMap(value: unknown): Suites | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const out: Suites = {}
  for (const [key, suite] of Object.entries(value as Record<string, unknown>)) {
    const parsed = testSuiteSchema.safeParse(suite)
    if (!parsed.success) return null
    out[key] = parsed.data
  }
  return out
}

/** The whole suite map as JSON — the escape hatch, exactly as Text mode is for
 * the definition. It stays lossless in both directions because the suite
 * schema is CLOSED: Twinlab owns every field, so there is nothing to drop on
 * the way in or invent on the way out.
 *
 * It is a separate dialog now rather than a tab inside the editor, because the
 * visual path is per-test and this is the only view of the whole set. */
export function SuitesJsonDialog({
  labName,
  suites,
  onClose,
}: {
  labName: string
  suites: Suites
  onClose: () => void
}) {
  const [text, setText] = useState(() => JSON.stringify(suites, null, 2))
  const save = useSaveSuites(labName, onClose)

  function onSave(): void {
    let value: unknown
    try {
      value = JSON.parse(text)
    } catch (err) {
      toast.error(err instanceof Error ? `Invalid JSON: ${err.message}` : 'Invalid JSON')
      return
    }
    const parsed = parseSuiteMap(value)
    if (parsed === null) {
      toast.error('That is not a suite map — the schema rejected it')
      return
    }
    save.mutate(parsed)
  }

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        className="flex max-h-[85vh] flex-col sm:max-w-4xl"
        onInteractOutside={(event) => event.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>Test suites as JSON</DialogTitle>
          <DialogDescription>
            The whole set, exactly as it is stored. Everything the visual editors do is expressible
            here, and nothing here is lost by going back — the suite schema is closed.
          </DialogDescription>
        </DialogHeader>
        <CodeEditor
          value={text}
          onChange={setText}
          language="json"
          lint
          className="max-h-[60vh] min-h-72 flex-1"
        />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={onSave} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
