import { useEffect, useRef } from 'react'

import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { LoggedLabEvent } from '@/lib/lab-event-store'
import { useLabActivity } from '@/lib/lab-event-store'
import type { Job, JobStep } from '@/lib/schemas'

/** What an operation did, in two tiers.
 *
 * The STEPS are the server's own record (contract delta 29): the phases that
 * never leave the backend — netlab create, the image pre-flight, host prep,
 * Ansible's per-node push, the config-time gate. They are durable, so they read
 * the same during the run, after it finishes, and next week.
 *
 * Beneath them, while the job is running, sits this session's live container
 * feed from the SSE stream. That one is finer-grained and faster but has no
 * history at all (module ring buffer, empty after a reload), so it is labelled
 * as such rather than presented as part of the record.
 *
 * Attributing container events to a job needs no correlation id: the per-lab
 * job mutex means at most one job owns a lab at a time, so "that lab's events
 * between the job's start and finish" is exact.
 */

const LEVEL_STYLES: Record<JobStep['level'], string> = {
  info: 'text-muted-foreground',
  warning: 'text-amber-600 dark:text-amber-500',
  error: 'text-destructive',
}

function StepRow({ step }: { step: JobStep }) {
  return (
    <li className="flex gap-2">
      <span className="shrink-0 font-mono text-xs text-muted-foreground tabular-nums">
        {new Date(step.at).toLocaleTimeString()}
      </span>
      <span className="min-w-0">
        <span className="font-mono text-xs">{step.code}</span>
        <span className={cn('ml-2 text-xs', LEVEL_STYLES[step.level])}>{step.message}</span>
      </span>
    </li>
  )
}

export function JobProgress({
  lab,
  job,
  steps,
  isPending,
}: {
  lab: string
  job: Pick<Job, 'status' | 'created_at' | 'finished_at'>
  steps: JobStep[]
  isPending: boolean
}) {
  const running = job.status === 'running'
  const activity = useLabActivity(lab)
  const logRef = useRef<HTMLDivElement>(null)

  // Follow the tail while the job runs: the interesting line is the newest.
  // Scrolling the container itself, not scrollIntoView, which would move the
  // dialog or sheet around it.
  useEffect(() => {
    if (!running) return
    const log = logRef.current
    if (log !== null) log.scrollTop = log.scrollHeight
  }, [running, steps.length, activity.length])

  // Only the container events this job is responsible for. `finished_at` bounds
  // it once the job is done so a later operation's churn cannot drift in.
  const from = new Date(job.created_at).getTime()
  const until = job.finished_at === null ? Infinity : new Date(job.finished_at).getTime()
  const events = activity.filter(
    (event): event is LoggedLabEvent =>
      event.source === 'lab' && event.receivedAt >= from && event.receivedAt <= until,
  )

  return (
    <div className="flex flex-col gap-2">
      <div
        ref={logRef}
        role="log"
        aria-label="Operation progress"
        aria-live={running ? 'polite' : 'off'}
        className="max-h-64 overflow-y-auto rounded-[2px] border bg-muted/30 p-2"
      >
        {isPending ? (
          <Skeleton className="h-4 w-2/3" />
        ) : steps.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            {running
              ? 'Waiting for the first step…'
              : 'This operation recorded no steps — it predates the step log.'}
          </p>
        ) : (
          <ul className="flex flex-col gap-1">
            {steps.map((step) => (
              <StepRow key={`${step.at}-${step.code}`} step={step} />
            ))}
          </ul>
        )}

        {running && events.length > 0 && (
          <ul className="mt-2 flex flex-col gap-1 border-t pt-2">
            {events.map((event) => (
              <li key={event.seq} className="flex gap-2 font-mono text-xs text-muted-foreground">
                <span className="shrink-0 tabular-nums">
                  {new Date(event.receivedAt).toLocaleTimeString()}
                </span>
                <span className="shrink-0">{event.node ?? '—'}</span>
                <span>{event.action}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {running && (
        <p className="text-xs text-muted-foreground">
          Steps come from the server and are kept with the operation; container events below them
          are live from this session only. netlab&apos;s own output does not stream, so a quiet
          stretch inside a step is that step working.
        </p>
      )}
    </div>
  )
}
