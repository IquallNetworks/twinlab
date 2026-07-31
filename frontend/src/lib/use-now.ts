import { useEffect, useState } from 'react'

/** A coarse clock for relative timestamps ("3m ago", elapsed counters), which
 * drift silently without a re-render. `enabled: false` freezes it, so a surface
 * with nothing in flight stops ticking. */
export function useNow(intervalMs: number, enabled = true): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!enabled) return
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs, enabled])
  return now
}
