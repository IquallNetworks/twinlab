import { useQuery } from '@tanstack/react-query'

import { allJobsQueryOptions } from '@/lib/queries'
import type { Job } from '@/lib/schemas'

// One cross-lab query (GET /jobs) backs every aggregate view. It replaced a
// fan-out of one query per lab merged client-side, so partial failure — a few
// labs loading, others erroring — is no longer a state that exists.

// Job events on the SSE stream announce submits and completions, so this is a
// FALLBACK only: the stream has no replay, and a reconnect silently misses
// whatever happened while it was down.
const JOB_POLL_MS = 15000

export function jobsRefetchInterval(live: boolean) {
  return live
    ? (query: { state: { data?: Job[] } }) =>
        query.state.data?.some((job) => job.status === 'running') ? JOB_POLL_MS : false
    : undefined
}

export interface AllJobs {
  jobs: Job[]
  isPending: boolean
  isError: boolean
}

/** Recent jobs across every readable lab, newest first (the server orders
 * them). `limit` bounds the page; `live` keeps a slow fallback poll running
 * while a running job is in view. */
export function useAllJobs(options?: { limit?: number; live?: boolean }): AllJobs {
  const { data, isPending, isError } = useQuery({
    ...allJobsQueryOptions(options?.limit ?? 50),
    refetchInterval: jobsRefetchInterval(options?.live ?? false),
  })
  return { jobs: data ?? [], isPending, isError }
}
