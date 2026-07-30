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
  showLab = false,
  limit,
}: {
  jobs: Job[]
  isPending: boolean
  isError: boolean
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
              </TableCell>
            </TableRow>
          ) : rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={colCount} className="py-8 text-center text-muted-foreground">
                <span className="font-mono text-xs tracking-wide uppercase">no operations</span>
              </TableCell>
            </TableRow>
          ) : (
            rows.map((job) => (
              <TableRow
                key={job.id}
                className="cursor-pointer"
                onClick={() => setSelected(job)}
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
