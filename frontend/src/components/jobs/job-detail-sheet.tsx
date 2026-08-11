import { useQuery } from '@tanstack/react-query'

import { JobProgress } from '@/components/jobs/job-progress'
import { Badge } from '@/components/ui/badge'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { formatDateTime, formatElapsed, jobStatusBadgeVariant } from '@/lib/format'
import { jobQueryOptions } from '@/lib/queries'
import type { Job } from '@/lib/schemas'
import { useNow } from '@/lib/use-now'

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <pre className="max-h-60 overflow-auto rounded-md bg-muted p-3 font-mono text-xs">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  )
}

/** Full detail of one async job: identity, timing (live elapsed while
 * running), what the operation DID (the step log, contract delta 29), the
 * submitted request, and the result or error envelope.
 *
 * `job` is the row the table was rendering; the sheet re-reads the job by id
 * because only the single-job endpoint carries steps. That also makes an open
 * sheet live — a running job's status and steps update in place. */
export function JobDetailSheet({ job, onClose }: { job: Job | null; onClose: () => void }) {
  const query = useQuery({
    ...jobQueryOptions(job?.lab_name ?? '', job?.id ?? '', job?.status === 'running'),
    enabled: job !== null,
  })
  // The fetched detail wins once it lands; until then the row keeps the sheet
  // populated, so opening it never flashes empty.
  const current = query.data ?? job
  const running = current?.status === 'running'
  const now = useNow(1000, running)

  return (
    <Sheet open={job !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="overflow-y-auto">
        {current && job && (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-center gap-2">
                <span className="font-mono">{current.kind}</span>
                <Badge variant={jobStatusBadgeVariant(current.status)}>{current.status}</Badge>
              </SheetTitle>
              <SheetDescription className="font-mono text-xs">
                {current.lab_name} · {current.id}
              </SheetDescription>
            </SheetHeader>

            <div className="flex flex-col gap-4 px-4 pb-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-xs text-muted-foreground">Submitted</div>
                  <div className="font-mono text-xs">{formatDateTime(current.created_at)}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">
                    {current.finished_at ? 'Finished' : 'Elapsed'}
                  </div>
                  <div className="font-mono text-xs">
                    {current.finished_at
                      ? formatDateTime(current.finished_at)
                      : formatElapsed(current.created_at, now)}
                  </div>
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <span className="text-xs text-muted-foreground">steps</span>
                <JobProgress
                  lab={current.lab_name}
                  job={current}
                  steps={query.data?.steps ?? []}
                  isPending={query.isPending}
                />
              </div>

              <JsonBlock label="request" value={current.request} />
              {current.error !== null && <JsonBlock label="error" value={current.error} />}
              {current.result !== null && <JsonBlock label="result" value={current.result} />}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
