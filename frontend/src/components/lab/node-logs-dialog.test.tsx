// @vitest-environment jsdom
//
// Following a log (delta 37) reads the stream with fetch, so a refusal shows
// the server's own message. Under EventSource a refusal (here the lab torn
// down while the dialog was open) arrived as a bare error and read "the
// stream stopped; follow again", which following again could never fix.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { NodeLogsDialog } from './node-logs-dialog'

afterEach(() => {
  vi.unstubAllGlobals()
})

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function sse(...chunks: string[]): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

/** Serve the snapshot read as an empty log and the stream read as `stream`. */
function serve(stream: () => Response): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      Promise.resolve(
        url.includes('/logs/stream')
          ? stream()
          : json(200, { lab_name: 'lab1', node_name: 'r1', container: 'clab-lab1-r1', logs: '' }),
      ),
    ),
  )
}

function follow(): void {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NodeLogsDialog name="lab1" node="r1" open onOpenChange={() => undefined} />
    </QueryClientProvider>,
  )
}

it('follows from the moment it opens, and Stop following shows the snapshot', async () => {
  serve(() => sse('event: log\ndata: {"stream":"stdout","line":"booting"}\n\n'))
  follow()
  expect(await screen.findByText(/booting/)).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Refresh' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Stop following' }))
  expect(await screen.findByText(/last 200 lines/)).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Refresh' })).toBeTruthy()
})

it("shows the server's refusal and offers to follow again", async () => {
  serve(() => json(409, { code: 'lab_not_running', message: "lab 'lab1' is not deployed", extras: {} }))
  follow()
  expect(await screen.findByText("lab 'lab1' is not deployed")).toBeTruthy()
  expect(screen.getByText(/could not follow/)).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Follow again' })).toBeTruthy()
})

it('shows the streamed lines, then that the log ended', async () => {
  serve(() =>
    sse(
      ': keepalive\n\n',
      'event: log\ndata: {"stream":"stdout","line":"booting"}\n\n',
      'event: log\ndata: {"stream":"stderr","line":"ready"}\n\nevent: end\ndata: {}\n\n',
    ),
  )
  follow()
  expect(await screen.findByText(/the log ended/)).toBeTruthy()
  expect(screen.getByText(/booting\s+ready/)).toBeTruthy()
})

it('reports a stream that closes without its end event as lost', async () => {
  serve(() => sse('event: log\ndata: {"stream":"stdout","line":"booting"}\n\n'))
  follow()
  expect(await screen.findByText(/the stream stopped/)).toBeTruthy()
})
