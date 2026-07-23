import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { labQueryOptions, labsQueryOptions } from '@/lib/queries'

/** Edit a lab's stored netlab definition. The change is persisted but does not
 * touch the running lab — a redeploy applies it. The lab's name is fixed by the
 * record, so a `name:` in the edited text is ignored by the backend. */
export function EditDefinitionDialog({ name, definition }: { name: string; definition: string }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(definition)

  const save = useMutation({
    mutationFn: () => api.updateLabDefinition(name, draft),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: labQueryOptions(name).queryKey }),
        queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey }),
      ])
      toast.success(`Definition updated. Redeploy ${name} to apply it.`)
      setOpen(false)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Update failed'),
  })

  // Reset the draft to the current definition each time the dialog opens.
  function onOpenChange(next: boolean) {
    if (next) setDraft(definition)
    setOpen(next)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline">Edit definition</Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit definition — {name}</DialogTitle>
          <DialogDescription>
            Update the stored netlab definition. This is saved but not applied until you redeploy.
          </DialogDescription>
        </DialogHeader>
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          spellCheck={false}
          className="min-h-72 font-mono text-xs"
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || draft.trim().length === 0}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
