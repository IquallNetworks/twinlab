import { useSyncExternalStore } from 'react'

import type { LabEvent } from '@/lib/schemas'

// Session-scoped log of the SSE lab events. There is no event-history
// endpoint, so this is a module-scope ring buffer: it survives route changes
// and resets on a full page load — the UI must present it as "since this
// session". Kept outside the query cache on purpose (it's a push log, not a
// fetchable resource).

export interface LoggedLabEvent extends LabEvent {
  // Monotonic per-session id — the React list key (events carry no id).
  seq: number
  receivedAt: number
}

const CAPACITY = 100

let seq = 0
// Immutable snapshot, replaced on every write so useSyncExternalStore
// consumers see a referential change.
let events: readonly LoggedLabEvent[] = []
const listeners = new Set<() => void>()

export function recordLabEvent(event: LabEvent): void {
  seq += 1
  const next = [{ ...event, seq, receivedAt: Date.now() }, ...events]
  events = next.length > CAPACITY ? next.slice(0, CAPACITY) : next
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function getSnapshot(): readonly LoggedLabEvent[] {
  return events
}

/** The session's lab events, newest first. */
export function useLabEventLog(): readonly LoggedLabEvent[] {
  return useSyncExternalStore(subscribe, getSnapshot)
}
