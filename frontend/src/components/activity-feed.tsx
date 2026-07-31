import { Link } from '@tanstack/react-router'

import { formatRelativeTime } from '@/lib/format'
import { useLabEventLog } from '@/lib/lab-event-store'
import { useNow } from '@/lib/use-now'

/** Live lab events from the SSE stream, newest first. Session-scoped by
 * nature — there is no server-side event history to backfill from. */
export function ActivityFeed({ limit = 12 }: { limit?: number }) {
  const events = useLabEventLog()
  const now = useNow(10_000)

  if (events.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        <span className="font-mono text-xs tracking-wide uppercase">no activity yet</span>
        <span className="mt-1 block">Live lab events appear here as they happen this session.</span>
      </p>
    )
  }

  return (
    <ul className="flex flex-col gap-1.5">
      {events.slice(0, limit).map((event) => (
        <li key={event.seq} className="flex items-baseline gap-2 text-sm">
          <span className="w-10 shrink-0 text-right font-mono text-xs text-muted-foreground">
            {formatRelativeTime(event.receivedAt, now)}
          </span>
          <Link
            to="/labs/$name"
            params={{ name: event.lab }}
            className="font-mono text-xs font-medium hover:text-primary hover:underline"
          >
            {event.lab}
          </Link>
          {event.node && <span className="font-mono text-xs">{event.node}</span>}
          <span className="text-muted-foreground">{event.action}</span>
        </li>
      ))}
    </ul>
  )
}
