import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
import { JobProgress } from '@/components/jobs/job-progress'
import { api, waitJob } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { jobQueryOptions, labInterfacesQueryOptions, labQueryOptions, labsQueryOptions } from '@/lib/queries'
import { deployResponseSchema } from '@/lib/schemas'
import type { Job } from '@/lib/schemas'

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

  // The submitted job, kept so the dialog can render ITS steps — the same
  // server-side log the jobs drawer shows, rather than a second progress model
  // that only exists while this dialog is open.
  const [job, setJob] = useState<Job | null>(null)

  const deploy = useMutation({
    mutationFn: async () => {
      const submitted = await api.deployLab(name, configure, skipChecks)
      setJob(submitted)
      return waitJob(name, submitted)
    },
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
    onError: (err) => toastError(err, 'Deploy failed'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['jobs', name] }),
  })

  // Polling is tied to the MUTATION's pending state, not to `job` being set:
  // `job` survives the operation (a failed deploy leaves the dialog open on
  // it), and this component stays mounted with the lab page, so a fixed
  // "running" would poll a finished job every 2s for as long as the page is
  // open. waitJob settles exactly when the job goes terminal.
  const jobQuery = useQuery({
    ...jobQueryOptions(name, job?.id ?? '', deploy.isPending),
    enabled: job !== null,
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
            {deploy.isPending ? `${verb}ing ${name}…` : `${verb} ${name}?`}
          </DialogTitle>
          <DialogDescription>
            {deploy.isPending
              ? 'The job runs on the server — closing this dialog does not cancel it.'
              : isRedeploy
                ? 'Rebuilds the lab from its stored definition, overwriting the running nodes. Any runtime state on the current nodes is lost.'
                : 'Deploys the lab from its stored definition.'}
          </DialogDescription>
        </DialogHeader>
        {deploy.isPending ? (
          job === null ? (
            // The gap between clicking and the 202 landing: short, but the
            // dialog must not go blank in it.
            <p className="text-xs text-muted-foreground">Submitting…</p>
          ) : (
            <JobProgress
              lab={name}
              job={jobQuery.data ?? job}
              steps={jobQuery.data?.steps ?? []}
              isPending={jobQuery.isPending}
            />
          )
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <Checkbox
                id="deploy-configure"
                checked={configure}
                onCheckedChange={(v) => setConfigure(v === true)}
              />
              <Label htmlFor="deploy-configure">
                Push configuration after deploy (adds minutes)
              </Label>
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
        )}
        <DialogFooter>
          {deploy.isPending ? (
            <Button variant="outline" onClick={() => setOpen(false)}>
              Close (keeps running)
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button onClick={() => deploy.mutate()}>{verb}</Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
