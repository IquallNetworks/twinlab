import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { labEventSchema } from '@/lib/schemas'

// Coalesce bursts (a deploy emits create/start/… in quick succession) into one
// refetch, and let it settle before firing so the read reflects the new state.
const DEBOUNCE_MS = 300

/** Subscribe to the backend SSE stream and refresh lab data when the topology
 * changes — so deploys, power actions, and out-of-band changes show up live
 * without polling. EventSource carries the session cookie (same-origin via the
 * dev proxy) and auto-reconnects if the connection drops; we close it on unmount.
 * All lab queries are keyed under ['labs'] (list, detail, interfaces), so one
 * prefix invalidation refreshes whatever is on screen for the affected data. */
export function useLabEvents(): void {
  const queryClient = useQueryClient()
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const source = new EventSource('/api/v1/events')

    source.onmessage = (event: MessageEvent<string>) => {
      let data: unknown
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }
      if (!labEventSchema.safeParse(data).success) return
      clearTimeout(timer)
      timer = setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ['labs'] })
      }, DEBOUNCE_MS)
    }

    return () => {
      clearTimeout(timer)
      source.close()
    }
  }, [queryClient])
}
