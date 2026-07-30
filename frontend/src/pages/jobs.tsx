import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { JobsTable } from '@/components/jobs/jobs-table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useAllJobs } from '@/lib/use-all-jobs'
import { useDocumentTitle } from '@/lib/use-document-title'

const STATUS_FILTERS = ['all', 'running', 'succeeded', 'failed'] as const
type StatusFilter = (typeof STATUS_FILTERS)[number]

/** The job center: recent async operations across every visible lab, newest
 * first, polling while any running job is in view. Aggregated client-side —
 * there is no cross-lab jobs endpoint yet. */
export function JobsPage() {
  useDocumentTitle('Operations')
  const queryClient = useQueryClient()
  const { jobs, isPending, isError, failedLabs } = useAllJobs({ live: true })
  const [status, setStatus] = useState<StatusFilter>('all')
  const filtered = status === 'all' ? jobs : jobs.filter((job) => job.status === status)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between">
        <div className="flex items-baseline gap-3">
          <h1 className="font-heading text-2xl font-semibold">Operations</h1>
          {!isPending && (
            <span className="font-mono text-xs text-muted-foreground">
              {filtered.length} {filtered.length === 1 ? 'job' : 'jobs'}
            </span>
          )}
        </div>
        <Select value={status} onValueChange={(value) => setStatus(value as StatusFilter)}>
          <SelectTrigger className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_FILTERS.map((s) => (
              <SelectItem key={s} value={s}>
                {s === 'all' ? 'All statuses' : s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="border bg-card/60">
        <JobsTable
          jobs={filtered}
          isPending={isPending}
          isError={isError}
          failedLabs={failedLabs}
          onRetry={() => void queryClient.invalidateQueries({ queryKey: ['jobs'] })}
          showLab
        />
      </div>
    </div>
  )
}
