import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { api } from '@/lib/api'
import { nodeLogLineSchema, type NodeLogLine } from '@/lib/schemas'
import { createSseParser } from '@/lib/sse'

// The tail both modes start from, and how much a followed log keeps: enough
// for a whole boot, bounded so a chatty node cannot grow the page forever.
const TAIL = 200
const KEEP_LINES = 5000
// Lines arrive one SSE event each; render them in batches, not per event.
const FLUSH_MS = 150

type StreamState =
  | { kind: 'connecting' }
  | { kind: 'live' }
  | { kind: 'ended' }
  | { kind: 'lost' }
  // The server said no before the first byte (the lab was torn down, the
  // node is gone, clab-api failed): its own message, not a guess at the cause.
  // A STOPPED node is not refused: it streams its tail, then `end`.
  | { kind: 'refused'; message: string }

/** Follow a node's log over the delta-37 stream while `active`.
 *
 * Read with `fetch` and lib/sse.ts rather than EventSource, which reports a
 * refusal as a bare error and hides the envelope. No automatic reconnect: the
 * stream has no resume point, so reconnecting would replay the tail; a dropped
 * stream is reported and the user follows again. */
function useFollowedLog(name: string, node: string, active: boolean, attempt: number) {
  const [lines, setLines] = useState<NodeLogLine[]>([])
  const [state, setState] = useState<StreamState>({ kind: 'connecting' })

  useEffect(() => {
    if (!active) return
    setLines([])
    setState({ kind: 'connecting' })
    const abort = new AbortController()
    const pending: NodeLogLine[] = []
    const flush = () => {
      if (pending.length === 0) return
      const batch = pending.splice(0)
      setLines((current) => [...current, ...batch].slice(-KEEP_LINES))
    }
    const timer = window.setInterval(flush, FLUSH_MS)
    let ended = false
    const parser = createSseParser((event) => {
      if (event.type === 'end') {
        ended = true
        return
      }
      if (event.type !== 'log') return
      let payload: unknown
      try {
        payload = JSON.parse(event.data)
      } catch {
        return
      }
      const parsed = nodeLogLineSchema.safeParse(payload)
      if (parsed.success) pending.push(parsed.data)
    })

    void (async () => {
      let reader: ReadableStreamDefaultReader<string>
      try {
        const resp = await api.openNodeLogStream(name, node, TAIL, abort.signal)
        if (resp.body === null) throw new Error('the log stream has no body')
        reader = resp.body.pipeThrough(new TextDecoderStream()).getReader()
      } catch (err) {
        if (abort.signal.aborted) return
        setState({ kind: 'refused', message: err instanceof Error ? err.message : String(err) })
        return
      }
      setState({ kind: 'live' })
      try {
        while (!ended) {
          const { done, value } = await reader.read()
          if (done) break
          parser.push(value)
        }
      } catch {
        // A dropped connection; reported as lost below unless we closed it.
      }
      if (abort.signal.aborted) return
      if (ended) void reader.cancel()
      flush()
      setState({ kind: ended ? 'ended' : 'lost' })
    })()

    return () => {
      abort.abort()
      window.clearInterval(timer)
    }
  }, [name, node, active, attempt])

  return { lines, state }
}

function followNote(state: StreamState, count: number): string {
  switch (state.kind) {
    case 'connecting':
      return 'connecting…'
    case 'live':
      return `following · ${count} lines`
    case 'ended':
      // The server also ends a follow after an hour (it is authorized once).
      return 'the log ended: the node stopped, or an hour of following passed'
    case 'lost':
      return 'the stream stopped; follow again to resume'
    case 'refused':
      return 'could not follow'
  }
}

/** Container logs for one node, followed live (delta 37) from the moment it
 * opens, since the newest lines are what a log is opened for; Stop following
 * turns it into a snapshot of the last 200 lines with a manual refresh.
 *
 * Owns its trigger button by default (the Connect drawer uses it that way).
 * Pass `open`/`onOpenChange` to drive it from somewhere a button cannot go —
 * the nodes table opens it from a menu item, where the trigger would be a
 * second, competing button. */
export function NodeLogsDialog({
  name,
  node,
  open: openProp,
  onOpenChange,
}: {
  name: string
  node: string
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false)
  const controlled = openProp !== undefined
  const open = controlled ? openProp : uncontrolledOpen
  const setOpen = controlled ? (onOpenChange ?? (() => {})) : setUncontrolledOpen
  // Every open starts following; closing resets it (onOpenChangeAll).
  const [follow, setFollow] = useState(true)
  // Bumped by "Follow again" to restart the stream from a fresh tail.
  const [attempt, setAttempt] = useState(0)
  // The snapshot, read only while not following; Refresh re-reads it.
  const { data, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['labs', name, 'logs', node],
    queryFn: () => api.nodeLogs(name, node, TAIL),
    enabled: open && !follow,
    staleTime: 0,
  })
  const followed = useFollowedLog(name, node, open && follow, attempt)

  // Keep the newest line in view, unless the reader has scrolled up to read.
  const pre = useRef<HTMLPreElement>(null)
  const stick = useRef(true)
  useEffect(() => {
    const element = pre.current
    if (element && stick.current) element.scrollTop = element.scrollHeight
  }, [followed.lines])

  function onOpenChangeAll(next: boolean) {
    if (!next) {
      setFollow(true)
      stick.current = true
    }
    setOpen(next)
  }

  const snapshot = isFetching
    ? 'Loading…'
    : isError
      ? error instanceof Error
        ? error.message
        : 'Failed to load logs'
      : (data?.logs ?? '').trim() || 'No log output.'
  const streamed =
    followed.state.kind === 'refused'
      ? followed.state.message
      : followed.lines.length > 0
        ? followed.lines.map((line) => line.line).join('\n')
        : followed.state.kind === 'live'
          ? 'Waiting for output…'
          : ''

  return (
    <Dialog open={open} onOpenChange={onOpenChangeAll}>
      {!controlled && (
        <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
          Logs
        </Button>
      )}
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Logs — {node}</DialogTitle>
          <DialogDescription>
            {data ? data.container : `clab node ${node}`} ·{' '}
            {follow ? followNote(followed.state, followed.lines.length) : `last ${TAIL} lines`}
          </DialogDescription>
        </DialogHeader>
        <pre
          ref={pre}
          onScroll={(event) => {
            const element = event.currentTarget
            stick.current =
              element.scrollHeight - element.scrollTop - element.clientHeight < 24
          }}
          className="max-h-[60vh] overflow-auto rounded-md bg-muted p-4 font-mono text-xs"
        >
          {follow ? streamed : snapshot}
        </pre>
        <div className="flex gap-2">
          {follow ? null : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => void refetch()}
              disabled={isFetching}
            >
              Refresh
            </Button>
          )}
          <Button
            variant={follow ? 'secondary' : 'outline'}
            size="sm"
            aria-pressed={follow}
            onClick={() => {
              stick.current = true
              setFollow((current) => !current)
            }}
          >
            {follow ? 'Stop following' : 'Follow'}
          </Button>
          {follow && ['ended', 'lost', 'refused'].includes(followed.state.kind) ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                stick.current = true
                setAttempt((current) => current + 1)
              }}
            >
              Follow again
            </Button>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}
