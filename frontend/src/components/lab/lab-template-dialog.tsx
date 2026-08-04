import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { labQueryOptions, networkTemplateQueryOptions } from '@/lib/queries'
import type { LabDetail } from '@/lib/schemas'

/** The "use as a template" toggle (delta 21): publish this lab's stored
 * definition into the network-template library as a LIVE entry (it follows
 * future edits), or withdraw it. Rendered from the lab header's ⋯ menu for
 * holders of the GLOBAL template:manage; state-driven open because a
 * DropdownMenuItem unmounts its subtree on select. */
export function LabTemplateDialog({
  lab,
  open,
  onOpenChange,
}: {
  lab: LabDetail
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const published = lab.template_published
  // The card text lives on the library entry, not the lab detail — fetch it
  // to prefill when editing an existing publication.
  const entry = useQuery({
    ...networkTemplateQueryOptions(lab.name),
    enabled: open && published,
  })
  const [description, setDescription] = useState('')

  useEffect(() => {
    if (!open) setDescription('')
  }, [open])
  useEffect(() => {
    if (open && published && entry.data !== undefined && description === '') {
      setDescription(entry.data.description)
    }
  }, [open, published, entry.data, description])

  const set = useMutation({
    mutationFn: (next: boolean) => api.setLabTemplate(lab.name, next, next ? description : null),
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['templates'] }),
        queryClient.invalidateQueries({ queryKey: labQueryOptions(lab.name).queryKey }),
      ])
      toast.success(
        result === null
          ? `${lab.name} withdrawn from the template library`
          : `${lab.name} is published as a network template`,
      )
      onOpenChange(false)
    },
    onError: (err) => toastError(err, 'Updating the template publication failed'),
  })

  const unauthored = lab.definition === null
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading">Use {lab.name} as a template</DialogTitle>
          <DialogDescription>
            Publishing serves this lab&apos;s stored definition as a network template to every
            authenticated user — a live view that follows future edits. New labs can start from it;
            each starts as an independent copy.
          </DialogDescription>
        </DialogHeader>

        {unauthored ? (
          <p className="text-sm text-muted-foreground">
            This lab has no definition yet — author one first, then publish it.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            <Label htmlFor="lab-template-description">Library description</Label>
            <Input
              id="lab-template-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="What this topology demonstrates"
            />
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          {published && (
            <Button
              variant="outline"
              size="sm"
              className="text-destructive"
              disabled={set.isPending}
              onClick={() => set.mutate(false)}
            >
              Withdraw
            </Button>
          )}
          <Button
            size="sm"
            disabled={unauthored || description.trim() === '' || set.isPending}
            onClick={() => set.mutate(true)}
          >
            {set.isPending ? 'Saving…' : published ? 'Update' : 'Publish'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
