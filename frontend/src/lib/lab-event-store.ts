import { useMemo, useSyncExternalStore } from 'react'

import type { JobEvent, LabEvent } from '@/lib/schemas'

// Session-scoped log of the SSE stream. There is no event-history endpoint,
// so this is a module-scope ring buffer: it survives route changes and resets
// on a full page load — the UI must present it as "since this session". Kept
// outside the query cache on purpose (it's a push log, not a fetchable
// resource).
//
// BOTH named events land here. The lab events are the container lifecycle
// (what the activity feed shows); the job events bracket them with the
// operation that caused them, which is what makes the pair readable as
// progress while a deploy runs.

interface Logged {
  // Monotonic per-session id — the React list key (events carry no id).
  seq: number
  receivedAt: number
}

// The discriminant is `source`, not `kind`: a JobEvent already has a `kind`
// of its own (deploy/configure/destroy/suite_run) and intersecting the two
// would collapse it to never.
export type LoggedLabEvent = Logged & LabEvent & { source: 'lab' }
export type LoggedJobEvent = Logged & JobEvent & { source: 'job' }
export type LoggedEvent = LoggedLabEvent | LoggedJobEvent

const CAPACITY = 200

let seq = 0
// Immutable snapshot, replaced on every write so useSyncExternalStore
// consumers see a referential change.
let events: readonly LoggedEvent[] = []
const listeners = new Set<() => void>()

function push(event: LoggedEvent): void {
  const next = [event, ...events]
  events = next.length > CAPACITY ? next.slice(0, CAPACITY) : next
  for (const listener of listeners) listener()
}

export function recordLabEvent(event: LabEvent): void {
  seq += 1
  push({ ...event, source: 'lab', seq, receivedAt: Date.now() })
}

export function recordJobEvent(event: JobEvent): void {
  seq += 1
  push({ ...event, source: 'job', seq, receivedAt: Date.now() })
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function getSnapshot(): readonly LoggedEvent[] {
  return events
}

/** Everything recorded this session, newest first. Derivations filter this —
 * never inside getSnapshot, which must return a stable reference. */
function useEventLog(): readonly LoggedEvent[] {
  return useSyncExternalStore(subscribe, getSnapshot)
}

/** The session's container-lifecycle events, newest first. */
export function useLabEventLog(): readonly LoggedLabEvent[] {
  const all = useEventLog()
  return useMemo(() => all.filter((event): event is LoggedLabEvent => event.source === 'lab'), [all])
}

/** One lab's events — both kinds — OLDEST first: this reads as a progress
 * log, which runs downward. */
export function useLabActivity(lab: string): readonly LoggedEvent[] {
  const all = useEventLog()
  return useMemo(
    () => all.filter((event) => event.lab === lab).slice().reverse(),
    [all, lab],
  )
}
