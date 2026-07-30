import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { recordLabEvent } from '@/lib/lab-event-store'
import { jobEventSchema, labEventSchema } from '@/lib/schemas'

// Coalesce bursts (a deploy emits create/start/… in quick succession) into one
// refetch, and let it settle before firing so the read reflects the new state.
const DEBOUNCE_MS = 300

/** Subscribe to the backend SSE stream and refresh on both of its events — so
 * deploys, power actions, out-of-band changes and job completions show up live
 * without polling. EventSource carries the session cookie (same-origin via the
 * dev proxy) and auto-reconnects if the connection drops; we close it on
 * unmount.
 *
 * The stream has NO replay, so a reconnect misses whatever happened while it
 * was down — surfaces that watch a running job keep a slow fallback poll. */
export function useLabEvents(): void {
  const queryClient = useQueryClient()
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const source = new EventSource('/api/v1/events')

    // All lab queries are keyed under ['labs'] (list, detail, interfaces,
    // links), so one prefix invalidation refreshes whatever is on screen; job
    // history is keyed under its own root to keep lab invalidations cheap.
    function refreshSoon() {
      clearTimeout(timer)
      timer = setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ['labs'] })
        void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      }, DEBOUNCE_MS)
    }

    function parse(event: MessageEvent<string>): unknown {
      try {
        return JSON.parse(event.data)
      } catch {
        return undefined
      }
    }

    source.addEventListener('lab', (event: MessageEvent<string>) => {
      const parsed = labEventSchema.safeParse(parse(event))
      if (!parsed.success) return
      // The activity log wants every event, so record before the debounce.
      recordLabEvent(parsed.data)
      refreshSoon()
    })

    source.addEventListener('job', (event: MessageEvent<string>) => {
      const parsed = jobEventSchema.safeParse(parse(event))
      if (!parsed.success) return
      // A submit or a completion: the job lists change either way, and a
      // finished deploy/destroy also changed the lab it ran on.
      refreshSoon()
    })

    return () => {
      clearTimeout(timer)
      source.close()
    }
  }, [queryClient])
}
