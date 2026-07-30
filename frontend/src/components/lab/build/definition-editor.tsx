import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

/** The Build tab's text mode: the plain-YAML escape hatch (netlab's syntax is
 * far richer than the visual builder's subset). The draft re-seeds from the
 * stored definition only while clean, so SSE-driven refetches never eat an
 * edit; a successful save (onSave resolves true) marks it clean again. */
export function DefinitionEditor({
  definition,
  saving,
  onSave,
  onDirtyChange,
}: {
  definition: string | null
  saving: boolean
  onSave: (text: string) => Promise<boolean>
  onDirtyChange: (dirty: boolean) => void
}) {
  const [draft, setDraft] = useState(definition ?? '')
  const [dirty, setDirtyState] = useState(false)

  const setDirty = (next: boolean) => {
    setDirtyState(next)
    onDirtyChange(next)
  }

  useEffect(() => {
    if (!dirty) setDraft(definition ?? '')
  }, [definition, dirty])

  return (
    <div className="flex flex-col gap-2">
      <Textarea
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value)
          setDirty(event.target.value !== (definition ?? ''))
        }}
        spellCheck={false}
        className="h-[max(24rem,calc(100vh-26rem))] resize-none font-mono text-xs"
        placeholder="netlab definition (provider, defaults.device, nodes, links, …)"
      />
      <div className="flex items-center justify-end gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!dirty || saving}
          onClick={() => {
            setDraft(definition ?? '')
            setDirty(false)
          }}
        >
          Reset
        </Button>
        <Button
          size="sm"
          disabled={!dirty || saving || draft.trim().length === 0}
          onClick={() => {
            void onSave(draft).then((saved) => {
              if (saved) setDirty(false)
            })
          }}
        >
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  )
}
