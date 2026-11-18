/** Just enough of the Server-Sent Events wire format to read a stream over
 * `fetch` (delta 37's followed log).
 *
 * EventSource cannot be used there: when the server refuses the stream (the
 * lab was torn down, the node is gone, clab-api failed) it reports a bare
 * `error` event and never exposes the response, so the envelope's message is
 * lost. Reading the
 * stream with `fetch` keeps the refusal readable, at the cost of parsing the
 * format here. Only what Twinlab's streams send is honoured: `event:` and
 * `data:` fields, comments, and every line ending the spec allows. `id:` and
 * `retry:` are ignored, since nothing here reconnects. */

export interface SseEvent {
  type: string
  data: string
}

export interface SseParser {
  /** Feed decoded text; complete events are delivered as they finish. */
  push(text: string): void
}

export function createSseParser(onEvent: (event: SseEvent) => void): SseParser {
  let buffer = ''
  // The previous chunk ended in \r: a \n opening this one belongs to it.
  let skipLf = false
  let type = ''
  let data: string[] = []

  function line(text: string): void {
    if (text === '') {
      // A blank line dispatches; an event with no data line is dropped.
      if (data.length > 0) onEvent({ type: type === '' ? 'message' : type, data: data.join('\n') })
      type = ''
      data = []
      return
    }
    if (text.startsWith(':')) return
    const colon = text.indexOf(':')
    const field = colon === -1 ? text : text.slice(0, colon)
    let value = colon === -1 ? '' : text.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') type = value
    else if (field === 'data') data.push(value)
  }

  return {
    push(text: string): void {
      buffer += skipLf && text.startsWith('\n') ? text.slice(1) : text
      skipLf = false
      for (;;) {
        const end = buffer.search(/\r\n|\r|\n/)
        if (end === -1) return
        const width = buffer.startsWith('\r\n', end) ? 2 : 1
        line(buffer.slice(0, end))
        buffer = buffer.slice(end + width)
        // A \r ending the chunk is a line end now, not a wait for its \n.
        if (width === 1 && buffer === '' && text.endsWith('\r')) skipLf = true
      }
    },
  }
}
