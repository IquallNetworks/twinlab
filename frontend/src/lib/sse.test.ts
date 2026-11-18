import { expect, it } from 'vitest'

import { createSseParser, type SseEvent } from './sse'

function parse(...chunks: string[]): SseEvent[] {
  const events: SseEvent[] = []
  const parser = createSseParser((event) => events.push(event))
  for (const chunk of chunks) parser.push(chunk)
  return events
}

it("reads the log stream's events, comments skipped", () => {
  const wire =
    ': keepalive\n\n' +
    'event: log\ndata: {"stream":"stdout","line":"a"}\n\n' +
    'event: end\ndata: {}\n\n'
  expect(parse(wire)).toEqual([
    { type: 'log', data: '{"stream":"stdout","line":"a"}' },
    { type: 'end', data: '{}' },
  ])
})

it('assembles an event split anywhere across chunks', () => {
  const wire = 'event: log\ndata: {"line":"boot"}\n\n'
  for (let cut = 1; cut < wire.length; cut += 1) {
    expect(parse(wire.slice(0, cut), wire.slice(cut))).toEqual([
      { type: 'log', data: '{"line":"boot"}' },
    ])
  }
})

it('accepts every line ending the spec allows, a split \\r\\n included', () => {
  expect(parse('event: a\r\ndata: 1\r\n\r\n', 'event: b\rdata: 2\r', '\r')).toEqual([
    { type: 'a', data: '1' },
    { type: 'b', data: '2' },
  ])
  expect(parse('data: x\r', '\ndata: y\r\n\r\n')).toEqual([{ type: 'message', data: 'x\ny' }])
})

it('does not dispatch an event before its blank line, nor one without data', () => {
  expect(parse('event: log\ndata: half')).toEqual([])
  expect(parse('event: lonely\n\n')).toEqual([])
})
