import { Badge } from '@/components/ui/badge'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { formatDateTime, formatElapsed, jobStatusBadgeVariant } from '@/lib/format'
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
 * running), the submitted request, and the result or error envelope. */
export function JobDetailSheet({ job, onClose }: { job: Job | null; onClose: () => void }) {
  const running = job?.status === 'running'
  const now = useNow(1000, running)

  return (
    <Sheet open={job !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="overflow-y-auto">
        {job && (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-center gap-2">
                <span className="font-mono">{job.kind}</span>
                <Badge variant={jobStatusBadgeVariant(job.status)}>{job.status}</Badge>
              </SheetTitle>
              <SheetDescription className="font-mono text-xs">
                {job.lab_name} · {job.id}
              </SheetDescription>
            </SheetHeader>

            <div className="flex flex-col gap-4 px-4 pb-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-xs text-muted-foreground">Submitted</div>
                  <div className="font-mono text-xs">{formatDateTime(job.created_at)}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">
                    {job.finished_at ? 'Finished' : 'Elapsed'}
                  </div>
                  <div className="font-mono text-xs">
                    {job.finished_at
                      ? formatDateTime(job.finished_at)
                      : formatElapsed(job.created_at, now)}
                  </div>
                </div>
              </div>

              <JsonBlock label="request" value={job.request} />
              {job.error !== null && <JsonBlock label="error" value={job.error} />}
              {job.result !== null && <JsonBlock label="result" value={job.result} />}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
