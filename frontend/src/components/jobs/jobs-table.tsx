import { useEffect, useState } from 'react'

import { JobDetailSheet } from '@/components/jobs/job-detail-sheet'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDateTime, formatElapsed, jobStatusBadgeVariant } from '@/lib/format'
import type { Job } from '@/lib/schemas'

function useNow(intervalMs: number, enabled: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!enabled) return
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs, enabled])
  return now
}

/** The shared jobs surface: used per-lab (Operations tab) and cross-lab
 * (dashboard, /jobs) — `showLab` adds the lab column in aggregate views.
 * Rows open the job detail sheet; running rows tick a live elapsed clock. */
export function JobsTable({
  jobs,
  isPending,
  isError,
  failedLabs = 0,
  onRetry,
  showLab = false,
  limit,
}: {
  jobs: Job[]
  isPending: boolean
  isError: boolean
  /** Aggregate views: how many labs' queries failed while others succeeded. */
  failedLabs?: number
  onRetry?: () => void
  showLab?: boolean
  limit?: number
}) {
  const [selected, setSelected] = useState<Job | null>(null)
  const anyRunning = jobs.some((job) => job.status === 'running')
  const now = useNow(1000, anyRunning)
  const colCount = showLab ? 5 : 4
  const rows = limit === undefined ? jobs : jobs.slice(0, limit)

  return (
    <>
      {!isError && failedLabs > 0 && (
        <p className="px-3 pt-2 text-xs text-destructive">
          Couldn&apos;t load operations for {failedLabs} {failedLabs === 1 ? 'lab' : 'labs'} — the
          list is partial.
        </p>
      )}
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {showLab && <TableHead>Lab</TableHead>}
            <TableHead>Kind</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Submitted</TableHead>
            <TableHead>Duration</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isPending ? (
            <TableRow>
              <TableCell colSpan={colCount}>
                <Skeleton className="h-6 w-full" />
              </TableCell>
            </TableRow>
          ) : isError ? (
            <TableRow>
              <TableCell colSpan={colCount} className="text-sm text-destructive">
                Failed to load operations.
                {onRetry !== undefined && (
                  <button
                    type="button"
                    className="ml-2 underline hover:text-foreground"
                    onClick={onRetry}
                  >
                    Retry
                  </button>
                )}
              </TableCell>
            </TableRow>
          ) : rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={colCount} className="py-8 text-center text-muted-foreground">
                <span className="font-mono text-xs tracking-wide uppercase">no operations</span>
                <span className="mt-1 block text-sm">
                  Deploy, configure and validation runs appear here.
                </span>
              </TableCell>
            </TableRow>
          ) : (
            rows.map((job) => (
              <TableRow
                key={job.id}
                className="cursor-pointer focus-visible:bg-muted/50 focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
                onClick={() => setSelected(job)}
                // Behaves as a button (opens the detail sheet), so it must be
                // keyboard-reachable and -operable too.
                tabIndex={0}
                role="button"
                aria-label={`${job.kind} ${job.status}, open details`}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    setSelected(job)
                  }
                }}
                title={job.error?.message}
              >
                {showLab && <TableCell className="font-mono text-xs">{job.lab_name}</TableCell>}
                <TableCell className="font-mono text-sm font-medium">{job.kind}</TableCell>
                <TableCell>
                  <Badge variant={jobStatusBadgeVariant(job.status)}>{job.status}</Badge>
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {formatDateTime(job.created_at)}
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {job.finished_at
                    ? formatElapsed(job.created_at, new Date(job.finished_at).getTime())
                    : job.status === 'running'
                      ? formatElapsed(job.created_at, now)
                      : '—'}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      <JobDetailSheet job={selected} onClose={() => setSelected(null)} />
    </>
  )
}
