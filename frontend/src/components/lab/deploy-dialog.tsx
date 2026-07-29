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
import { api, waitJob } from '@/lib/api'
import { labInterfacesQueryOptions, labQueryOptions, labsQueryOptions } from '@/lib/queries'
import { deployResponseSchema } from '@/lib/schemas'

/** Deploy a lab from its stored definition — the lifecycle split's final step,
 * and the ONLY deploy verb: fresh after create/destroy, overwrite-in-place when
 * the lab is already up (redeploy). Optionally pushes config after. The deploy
 * is an async job polled to its terminal state. */
export function DeployDialog({
  name,
  hasDefinition,
  isRedeploy,
}: {
  name: string
  hasDefinition: boolean
  isRedeploy: boolean
}) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [configure, setConfigure] = useState(false)
  const [skipChecks, setSkipChecks] = useState(false)
  const verb = isRedeploy ? 'Redeploy' : 'Deploy'

  const deploy = useMutation({
    mutationFn: async () => waitJob(name, await api.deployLab(name, configure, skipChecks)),
    onSuccess: async (job) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: labQueryOptions(name).queryKey }),
        queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey }),
        queryClient.invalidateQueries({ queryKey: labInterfacesQueryOptions(name).queryKey }),
      ])
      const result = deployResponseSchema.parse(job.result)
      if (result.status === 'validation_failed') {
        toast.error(`Deployed and configured ${name}, but config-time validation failed`)
      } else if (result.status === 'config_failed') {
        toast.error(`Deployed ${name}, but the config push failed on at least one node`)
      } else {
        toast.success(
          result.status === 'configured'
            ? `Deployed and configured ${name}`
            : `Deployed ${name} (${result.nodes.length} nodes)`,
        )
      }
      setOpen(false)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Deploy failed'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['jobs', name] }),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          disabled={!hasDefinition}
          title={hasDefinition ? undefined : 'Author a definition first'}
        >
          {verb}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {verb} {name}?
          </DialogTitle>
          <DialogDescription>
            {isRedeploy
              ? 'Rebuilds the lab from its stored definition, overwriting the running nodes. Any runtime state on the current nodes is lost.'
              : 'Deploys the lab from its stored definition.'}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Checkbox
              id="deploy-configure"
              checked={configure}
              onCheckedChange={(v) => setConfigure(v === true)}
            />
            <Label htmlFor="deploy-configure">Push configuration after deploy (adds minutes)</Label>
          </div>
          {configure && (
            <div className="flex items-center gap-2 pl-6">
              <Checkbox
                id="deploy-skip-checks"
                checked={skipChecks}
                onCheckedChange={(v) => setSkipChecks(v === true)}
              />
              <Label htmlFor="deploy-skip-checks" className="text-muted-foreground">
                Skip config-time checks
              </Label>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={() => deploy.mutate()} disabled={deploy.isPending}>
            {deploy.isPending ? `${verb}ing…` : verb}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
