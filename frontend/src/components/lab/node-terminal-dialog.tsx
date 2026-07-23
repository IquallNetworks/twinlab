import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Protocol = 'ssh' | 'shell'
type Status = 'connecting' | 'open' | 'closed'

// Server→client frames from clab-api's terminal stream (output is base64).
interface ServerFrame {
  type: 'ready' | 'output' | 'exit'
  data?: string
}

/** Build the same-origin WebSocket URL for the terminal proxy. The dev server
 * proxies /api/v1 (ws: true) to the backend, and prod is served same-origin, so
 * host + scheme come straight from the page. */
function terminalUrl(
  name: string,
  node: string,
  protocol: Protocol,
  sshUsername: string,
  cols: number,
  rows: number,
) {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const path = `/api/v1/labs/${encodeURIComponent(name)}/nodes/${encodeURIComponent(node)}/terminal`
  const params = new URLSearchParams({ protocol, cols: String(cols), rows: String(rows) })
  // ssh only, and only when set — empty leaves clab-api's default user in place.
  if (protocol === 'ssh' && sshUsername.trim() !== '') params.set('ssh_username', sshUsername.trim())
  return `${scheme}://${window.location.host}${path}?${params.toString()}`
}

/** Decode a base64 output frame to raw bytes; xterm renders the bytes itself, so
 * multibyte UTF-8 survives (a binary string would mangle it). */
function decodeOutput(data: string): Uint8Array {
  return Uint8Array.from(atob(data), (c) => c.charCodeAt(0))
}

/** One live terminal: an xterm instance bound to a fresh proxy WebSocket. Mounted
 * only while the dialog is open and remounted (via `key`) when the protocol
 * changes, so setup/teardown track the connection's whole lifecycle. */
function TerminalSession({
  name,
  node,
  protocol,
  sshUsername,
}: {
  name: string
  node: string
  protocol: Protocol
  sshUsername: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<Status>('connecting')
  const [detail, setDetail] = useState('')

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const term = new Terminal({
      fontSize: 13,
      fontFamily: 'var(--font-mono, monospace)',
      cursorBlink: true,
      theme: { background: '#0a0a0a' },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(container)
    fit.fit()

    const ws = new WebSocket(terminalUrl(name, node, protocol, sshUsername, term.cols, term.rows))

    ws.onopen = () => setStatus('open')
    ws.onmessage = (event) => {
      if (typeof event.data !== 'string') return
      let frame: ServerFrame
      try {
        frame = JSON.parse(event.data) as ServerFrame
      } catch {
        return
      }
      if (frame.type === 'output' && frame.data !== undefined) {
        term.write(decodeOutput(frame.data))
      } else if (frame.type === 'exit') {
        term.write('\r\n\x1b[90m[session ended]\x1b[0m\r\n')
      }
    }
    ws.onclose = (event) => {
      setStatus('closed')
      if (event.reason) setDetail(event.reason)
    }

    const input = term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'input', data }))
    })

    // Refit on container resize and tell the far end the new dimensions.
    const observer = new ResizeObserver(() => {
      fit.fit()
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
    })
    observer.observe(container)
    term.focus()

    return () => {
      observer.disconnect()
      input.dispose()
      ws.close()
      term.dispose()
    }
  }, [name, node, protocol, sshUsername])

  return (
    <div className="flex flex-col gap-2">
      <div ref={containerRef} className="h-[60vh] w-full overflow-hidden rounded-md bg-[#0a0a0a] p-2" />
      <p className="text-muted-foreground text-xs">
        {status === 'connecting' && 'Connecting…'}
        {status === 'open' && `Connected · ${protocol}`}
        {status === 'closed' && `Disconnected${detail ? ` · ${detail}` : ''}`}
      </p>
    </div>
  )
}

/** "Console" button + dialog: an in-browser terminal into a node over the WS
 * proxy. Protocol defaults to ssh, with shell as an option; gated by the caller
 * on lab:terminal and the node being up. */
export function NodeTerminalDialog({ name, node }: { name: string; node: string }) {
  const [open, setOpen] = useState(false)
  const [protocol, setProtocol] = useState<Protocol>('ssh')
  const [username, setUsername] = useState('')
  // The committed connection params. Editing the username input doesn't reconnect
  // until applied (Enter / Reconnect), so typing doesn't kill a live session; the
  // bumping nonce remounts TerminalSession for a clean reconnect.
  const [applied, setApplied] = useState<{ protocol: Protocol; username: string; nonce: number }>({
    protocol: 'ssh',
    username: '',
    nonce: 0,
  })

  function connect(next: Protocol) {
    setProtocol(next)
    setApplied((a) => ({ protocol: next, username, nonce: a.nonce + 1 }))
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        Console
      </Button>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Console — {node}</DialogTitle>
          <DialogDescription>Interactive terminal into the node over the lab proxy.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex items-center gap-1">
            {(['ssh', 'shell'] as const).map((p) => (
              <Button
                key={p}
                variant={protocol === p ? 'default' : 'outline'}
                size="sm"
                onClick={() => connect(p)}
              >
                {p}
              </Button>
            ))}
          </div>
          {protocol === 'ssh' && (
            <div className="flex items-end gap-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="ssh-username" className="text-xs">
                  SSH username
                </Label>
                <Input
                  id="ssh-username"
                  className="h-8 w-40"
                  placeholder="clab-api default"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') connect('ssh')
                  }}
                />
              </div>
              <Button variant="outline" size="sm" onClick={() => connect('ssh')}>
                Reconnect
              </Button>
            </div>
          )}
        </div>
        {open && (
          <TerminalSession
            key={applied.nonce}
            name={name}
            node={node}
            protocol={applied.protocol}
            sshUsername={applied.username}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
