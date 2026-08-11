import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
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
import { toastError } from '@/lib/error-toast'
import { useLabActivity } from '@/lib/lab-event-store'
import { labInterfacesQueryOptions, labQueryOptions, labsQueryOptions } from '@/lib/queries'
import { deployResponseSchema } from '@/lib/schemas'

/** What the SSE stream can tell us while a deploy runs. It is a live feed of
 * CONTAINER lifecycle plus the job's own submit/finish — not the job's
 * internals: netlab's output, the image pre-flight and Ansible's per-node
 * config push never leave the backend, so a long quiet stretch after the
 * containers are up is the config push working, not a stall. Said plainly
 * below rather than left to be guessed. */
function DeployProgress({ name }: { name: string }) {
  const events = useLabActivity(name)
  const logRef = useRef<HTMLDivElement>(null)
  // Follow the tail: the interesting line is always the newest one. Scrolling
  // the container directly rather than scrollIntoView, which would also move
  // the dialog itself.
  useEffect(() => {
    const log = logRef.current
    if (log !== null) log.scrollTop = log.scrollHeight
  }, [events.length])

  return (
    <div className="flex flex-col gap-2">
      <div
        ref={logRef}
        role="log"
        aria-label="Deploy progress"
        aria-live="polite"
        className="h-48 overflow-y-auto rounded-[2px] border bg-muted/30 p-2 font-mono text-xs"
      >
        {events.length === 0 ? (
          <p className="text-muted-foreground">Waiting for the first event…</p>
        ) : (
          events.map((event) => (
            <div key={event.seq} className="flex gap-2">
              <span className="shrink-0 text-muted-foreground">
                {new Date(event.receivedAt).toLocaleTimeString()}
              </span>
              {event.source === 'job' ? (
                <span className="text-primary">
                  {event.kind} {event.status === 'running' ? 'submitted' : event.status}
                </span>
              ) : (
                <>
                  <span className="shrink-0">{event.node ?? '—'}</span>
                  <span className="text-muted-foreground">{event.action}</span>
                </>
              )}
            </div>
          ))
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        Container events, live from this session. The config push and netlab&apos;s own output do
        not stream — a quiet stretch after the nodes appear is normal.
      </p>
    </div>
  )
}

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
    onError: (err) => toastError(err, 'Deploy failed'),
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
          <DeployProgress name={name} />
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
