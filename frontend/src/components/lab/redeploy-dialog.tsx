import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { labInterfacesQueryOptions, labQueryOptions, labsQueryOptions } from '@/lib/queries'

/** Rebuild a lab from its stored definition. Overwrites the running lab if it is
 * up, or deploys fresh if it was destroyed. Optionally re-pushes config after. */
export function RedeployDialog({ name }: { name: string }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [configure, setConfigure] = useState(false)
  const [skipChecks, setSkipChecks] = useState(false)

  const redeploy = useMutation({
    mutationFn: () => api.redeployLab(name, configure, skipChecks),
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: labQueryOptions(name).queryKey }),
        queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey }),
        queryClient.invalidateQueries({ queryKey: labInterfacesQueryOptions(name).queryKey }),
      ])
      if (result.status === 'validation_failed') {
        toast.error(`Redeployed and configured ${name}, but config-time validation failed`)
      } else {
        toast.success(
          result.status === 'configured'
            ? `Redeployed and configured ${name}`
            : `Redeployed ${name} (${result.nodes.length} nodes)`,
        )
      }
      setOpen(false)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Redeploy failed'),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">Redeploy</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Redeploy {name}?</DialogTitle>
          <DialogDescription>
            Rebuilds the lab from its stored definition, overwriting the running nodes. Any runtime
            state on the current nodes is lost.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Checkbox
              id="redeploy-configure"
              checked={configure}
              onCheckedChange={(v) => setConfigure(v === true)}
            />
            <Label htmlFor="redeploy-configure">Push configuration after redeploy</Label>
          </div>
          {configure && (
            <div className="flex items-center gap-2 pl-6">
              <Checkbox
                id="redeploy-skip-checks"
                checked={skipChecks}
                onCheckedChange={(v) => setSkipChecks(v === true)}
              />
              <Label htmlFor="redeploy-skip-checks" className="text-muted-foreground">
                Skip config-time checks
              </Label>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={() => redeploy.mutate()} disabled={redeploy.isPending}>
            {redeploy.isPending ? 'Redeploying…' : 'Redeploy'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
