import { useQueries, useQuery } from '@tanstack/react-query'

import { labJobsQueryOptions, labsQueryOptions } from '@/lib/queries'
import type { Job } from '@/lib/schemas'

// There is no cross-lab jobs endpoint (only GET /labs/{name}/jobs), so the
// aggregate view fans out one query per visible lab and merges client-side.
// Bounded and fine at realistic fleet sizes; the real fix is the parked
// backend item (global jobs listing / SSE job events).

// SSE lab events don't reliably signal job completion (a suite run changes no
// topology), so surfaces that watch running jobs poll while one is visible.
const JOB_POLL_MS = 4000

export function jobsRefetchInterval(live: boolean) {
  return live
    ? (query: { state: { data?: Job[] } }) =>
        query.state.data?.some((job) => job.status === 'running') ? JOB_POLL_MS : false
    : undefined
}

export interface AllJobs {
  jobs: Job[]
  isPending: boolean
  /** Every fan-out query failed — nothing at all to show. */
  isError: boolean
  /** Labs whose jobs query failed while others succeeded: the merged list is
   * partial, and consumers surface that instead of blanking the table. */
  failedLabs: number
}

/** Recent jobs across labs, newest first. `maxLabs` bounds the fan-out to the
 * most recently updated labs (omit for all); `live` polls any lab whose last
 * page contains a running job. Query keys are the shared ['jobs', name], so
 * SSE invalidation and the per-lab surfaces stay coherent. */
export function useAllJobs(options?: { maxLabs?: number; live?: boolean }): AllJobs {
  const { data: labs } = useQuery(labsQueryOptions)
  const names = (labs ?? [])
    .slice()
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .slice(0, options?.maxLabs)
    .map((lab) => lab.name)

  return useQueries({
    queries: names.map((name) => ({
      ...labJobsQueryOptions(name),
      refetchInterval: jobsRefetchInterval(options?.live ?? false),
    })),
    combine: (results) => ({
      jobs: results
        .flatMap((result) => result.data ?? [])
        .sort((a, b) => b.created_at.localeCompare(a.created_at)),
      isPending: names.length > 0 && results.some((result) => result.isPending),
      isError: results.length > 0 && results.every((result) => result.isError),
      failedLabs: results.filter((result) => result.isError).length,
    }),
  })
}
