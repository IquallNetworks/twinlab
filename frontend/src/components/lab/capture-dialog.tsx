import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { formatBytes } from '@/lib/format'
import { attachmentFilename, completePcapng } from '@/lib/pcapng'
import type { LabLink, LabNodeState } from '@/lib/schemas'

// The server's bounds (delta 36), mirrored so the form refuses what it would.
const MAX_SECONDS = 1800
const DEFAULT_SECONDS = 30

type Phase =
  | { kind: 'form' }
  | { kind: 'capturing'; startedAt: number }
  // Ran its full course with nobody clicking: the file waits for a click,
  // since a download nobody asked for is what browsers hold back or prompt
  // about (Chrome blocks a second automatic one from the same page).
  | { kind: 'finished'; file: Uint8Array<ArrayBuffer>; filename: string }
  | { kind: 'saved'; filename: string; bytes: number; stopped: boolean }
  | { kind: 'failed'; message: string }

function target(endpoint: { node: string; interface: string }): string {
  return `${endpoint.node}:${endpoint.interface}`
}

function parseWhole(text: string, min: number, max: number): number | null {
  if (!/^\d+$/.test(text.trim())) return null
  const value = Number(text)
  return value >= min && value <= max ? value : null
}

function saveFile(bytes: Uint8Array<ArrayBuffer>, filename: string): void {
  const url = URL.createObjectURL(new Blob([bytes], { type: 'application/x-pcapng' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  // The click has started the download by the time this runs.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Capture one link's traffic to a pcapng file (delta 36).
 *
 * The page fetches the stream itself rather than following a download link:
 * a link cannot show the server's refusal (the browser only reports a failed
 * download) and cannot stop early and keep what arrived. The cost is that the
 * capture sits in memory until it is saved, so very long or busy captures
 * belong to the client library or curl. Stop cuts the file at the last whole
 * pcapng block, so Wireshark reads it without a truncation warning, and saves
 * it at once, on the strength of that click; a capture that ends by itself
 * waits for Save file instead. */
export function CaptureDialog({
  name,
  link,
  nodes,
}: {
  name: string
  link: LabLink
  nodes: LabNodeState[]
}) {
  const running = (node: string) => nodes.find((n) => n.name === node)?.state === 'running'
  // Both ends of a point-to-point link see the same packets, so one is the
  // useful default; the rest are a tick away.
  const firstRunning = link.endpoints.find((endpoint) => running(endpoint.node))

  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [seconds, setSeconds] = useState(String(DEFAULT_SECONDS))
  const [packetLimit, setPacketLimit] = useState('')
  const [phase, setPhase] = useState<Phase>({ kind: 'form' })
  const [received, setReceived] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  const controller = useRef<AbortController | null>(null)
  // Set when the dialog closes mid-capture: the capture is dropped, not saved.
  const discard = useRef(false)

  // Abort whatever is in flight if the component goes away.
  useEffect(() => () => controller.current?.abort(), [])

  useEffect(() => {
    if (phase.kind !== 'capturing') return
    const timer = window.setInterval(() => setNow(Date.now()), 500)
    return () => window.clearInterval(timer)
  }, [phase.kind])

  const duration = parseWhole(seconds, 1, MAX_SECONDS)
  const limit =
    packetLimit.trim() === '' ? null : parseWhole(packetLimit, 1, Number.MAX_SAFE_INTEGER)
  const limitValid = packetLimit.trim() === '' || limit !== null
  const canStart = selected.length > 0 && duration !== null && limitValid

  function openDialog() {
    setSelected(firstRunning ? [target(firstRunning)] : [])
    setPhase({ kind: 'form' })
    setOpen(true)
  }

  function onOpenChange(next: boolean) {
    if (!next && phase.kind === 'capturing') {
      discard.current = true
      controller.current?.abort()
    }
    setOpen(next)
  }

  async function start() {
    if (duration === null) return
    const abort = new AbortController()
    controller.current = abort
    discard.current = false
    const chunks: Uint8Array[] = []
    let total = 0
    let filename = `${name}-capture.pcapng`
    let streaming = false
    setReceived(0)
    setNow(Date.now())
    setPhase({ kind: 'capturing', startedAt: Date.now() })
    try {
      const resp = await api.openCapture(
        name,
        { targets: selected, durationSeconds: duration, packetLimit: limit },
        abort.signal,
      )
      filename = attachmentFilename(resp.headers.get('Content-Disposition')) ?? filename
      if (resp.body === null) throw new Error('the capture response has no body')
      streaming = true
      const reader = resp.body.getReader()
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        chunks.push(value)
        total += value.length
        setReceived(total)
      }
    } catch (err) {
      // Closed mid-capture, or stopped before the first byte: nothing to keep.
      if (discard.current || (abort.signal.aborted && !streaming)) {
        setPhase({ kind: 'form' })
        return
      }
      if (!abort.signal.aborted) {
        setPhase({ kind: 'failed', message: err instanceof Error ? err.message : String(err) })
        return
      }
      // Stopped mid-stream: save what arrived, below.
    }
    if (discard.current) {
      setPhase({ kind: 'form' })
      return
    }
    const file = completePcapng(chunks)
    if (!abort.signal.aborted) {
      setPhase({ kind: 'finished', file, filename })
      return
    }
    save(file, filename, true)
  }

  function save(file: Uint8Array<ArrayBuffer>, filename: string, stopped: boolean) {
    saveFile(file, filename)
    setPhase({ kind: 'saved', filename, bytes: file.length, stopped })
  }

  const elapsed = phase.kind === 'capturing' ? Math.floor((now - phase.startedAt) / 1000) : 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <Button
        variant="outline"
        size="sm"
        onClick={openDialog}
        disabled={firstRunning === undefined}
        title={firstRunning === undefined ? 'No endpoint of this link is running' : undefined}
      >
        Capture
      </Button>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Capture — {link.name ?? `link #${link.index}`}</DialogTitle>
          <DialogDescription>
            Saves the traffic on the chosen interfaces as one pcapng file, for Wireshark.
          </DialogDescription>
        </DialogHeader>

        {phase.kind === 'form' || phase.kind === 'failed' ? (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <span className="text-muted-foreground text-xs">Interfaces</span>
              {link.endpoints.map((endpoint) => {
                const value = target(endpoint)
                const id = `capture-${link.index}-${value}`
                const up = running(endpoint.node)
                return (
                  <div key={value} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      id={id}
                      checked={selected.includes(value)}
                      disabled={!up}
                      onCheckedChange={(checked) =>
                        setSelected((current) =>
                          checked === true
                            ? [...current, value]
                            : current.filter((t) => t !== value),
                        )
                      }
                    />
                    <Label htmlFor={id} className="font-mono text-xs font-normal">
                      {value}
                    </Label>
                    {!up ? (
                      <span className="text-muted-foreground text-xs">node not running</span>
                    ) : null}
                  </div>
                )
              })}
              {link.endpoints.length === 2 ? (
                <p className="text-muted-foreground text-xs">
                  Both ends of a point-to-point link see the same packets; one is usually
                  enough.
                </p>
              ) : null}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <Label htmlFor={`capture-seconds-${link.index}`}>Duration (seconds)</Label>
                <Input
                  id={`capture-seconds-${link.index}`}
                  inputMode="numeric"
                  value={seconds}
                  onChange={(event) => setSeconds(event.target.value)}
                  aria-invalid={duration === null}
                />
                {duration === null ? (
                  <span className="text-destructive text-xs">1 to {MAX_SECONDS} seconds</span>
                ) : null}
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor={`capture-limit-${link.index}`}>Packet limit (optional)</Label>
                <Input
                  id={`capture-limit-${link.index}`}
                  inputMode="numeric"
                  placeholder="none"
                  value={packetLimit}
                  onChange={(event) => setPacketLimit(event.target.value)}
                  aria-invalid={!limitValid}
                />
                {!limitValid ? (
                  <span className="text-destructive text-xs">a whole number, at least 1</span>
                ) : null}
              </div>
            </div>
            {phase.kind === 'failed' ? (
              <p className="text-destructive text-sm" role="alert">
                {phase.message}
              </p>
            ) : null}
          </div>
        ) : phase.kind === 'capturing' ? (
          <div className="flex flex-col gap-1 text-sm" aria-live="polite">
            <span className="font-mono text-xs">{selected.join(', ')}</span>
            <span>
              Capturing… {Math.min(elapsed, duration ?? elapsed)} s of {duration} s ·{' '}
              {formatBytes(received)}
            </span>
            <span className="text-muted-foreground text-xs">
              Stop saves what has arrived. Closing this dialog drops the capture.
            </span>
          </div>
        ) : phase.kind === 'finished' ? (
          <div className="flex flex-col gap-1 text-sm" aria-live="polite">
            <span>
              Capture finished: <span className="font-mono text-xs">{phase.filename}</span> (
              {formatBytes(phase.file.length)}).
            </span>
            <span className="text-muted-foreground text-xs">
              Closing this dialog without saving drops it.
            </span>
          </div>
        ) : (
          <div className="flex flex-col gap-1 text-sm" aria-live="polite">
            <span>
              Saved <span className="font-mono text-xs">{phase.filename}</span> (
              {formatBytes(phase.bytes)}){phase.stopped ? ', stopped early' : ''}.
            </span>
            <span className="text-muted-foreground text-xs">
              Your browser&apos;s downloads list has the file.
            </span>
          </div>
        )}

        <DialogFooter>
          {phase.kind === 'capturing' ? (
            <Button variant="outline" onClick={() => controller.current?.abort()}>
              Stop and save
            </Button>
          ) : phase.kind === 'finished' ? (
            <Button onClick={() => save(phase.file, phase.filename, false)}>Save file</Button>
          ) : phase.kind === 'saved' ? (
            <Button variant="outline" onClick={() => setPhase({ kind: 'form' })}>
              Capture again
            </Button>
          ) : (
            <Button onClick={() => void start()} disabled={!canStart}>
              Start capture
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
