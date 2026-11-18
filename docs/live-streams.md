# Live streams: packet capture and log following

**Status: implemented 2026-11-17, awaiting review.** Verified live: the blackbox tests below,
and both features driven in a browser against a deployed FRR lab. Contract deltas 36 (packet capture) and 37
(log following). Both are thin passthroughs over endpoints that clab-api gained after v0.5.0, and
were picked from the v0.10.0 review on the maintainer's request. The third candidate from that
review, resumable terminal sessions, is deferred (see the end).

## Why

Twinlab offered no way to see a lab's traffic: an operator who wanted a capture had to get a
shell on the host and find the node's network namespace. And node logs were a snapshot of the
last 200 lines, so watching a node boot meant pressing Refresh.

clab-api v0.10.0 serves both natively, and both were probed live on a deployed lab before this
design:

- `GET /labs/{lab}/capture/stream` captures named lab interfaces through packet sockets in the
  nodes' namespaces (no Edgeshark) and streams one pcapng section, flushed per block. It works on
  Twinlab's inline-deployed labs, because clab-api saves the inline topology it deployed. The
  capture stops when the client disconnects (checked in the node's `/proc/net/packet`), and it
  takes clab-api's process-wide lock only while loading the lab, so a long capture blocks no one.
- `GET /labs/{lab}/nodes/{node}/logs?follow=true` streams NDJSON, one object per log line, with
  a blank line every 25 seconds while the node is quiet. It now accepts the short node name.

## Delta 36: `GET /labs/{name}/capture`

```
GET /labs/{name}/capture?target=r1:eth1&target=r2:eth1&duration_seconds=30
    [&packet_limit=N][&snap_length=N]
-> 200 application/x-pcapng, Content-Disposition: attachment; filename="<lab>-<UTC>.pcapng"
```

- **Permission: `lab:read`.** A capture observes the lab and changes nothing, the same tier as
  node logs, netem show and the facts, which already carry the lab's whole configuration.
- **`target`**: 1 to 16, each `<node>:<interface>`, split at the first colon. The interface is
  the container-side name the link table serves as `LinkEndpoint.interface`, or its alias. Only
  lab link interfaces are capturable; the management interface is not.
- **`duration_seconds` is required**, 1 to 1800. clab-api would capture until the client
  disconnects, but a forgotten download should not run for hours, and the proxy in front of the
  backend cuts a response that sends nothing for an hour (nginx `proxy_read_timeout 1h`, and a
  quiet link sends nothing). 30 minutes keeps a wide margin under it.
- **`packet_limit`** (≥ 1) ends the capture early. **`snap_length`** (64 to 262144 bytes, clab-api's
  default being the maximum) truncates each packet.
- The capture ends at whichever comes first: the duration, the packet limit, or the client
  disconnecting.

Errors are the usual envelope **before the first byte**: 409 `lab_not_running` (the record is not
`deployed`), 422 `invalid_capture_target` (a malformed target, or one clab-api does not accept:
an unknown node or interface), 409 `node_not_running`, 502 `upstream_error`. After the first byte
a failure can only end the stream, so a stream that ends before its duration is not proof of
success. The pcapng header arrives at once, so a capture that saw no packets is a valid empty
file, not an error.

**Not done:** no capture job, history or storage. The bytes stream through the backend and are
never kept, so there is nothing to clean up and no quota to enforce. A link selector
(`?link=<index>`) was considered and left out: the link table already gives a client every
endpoint's target, and a selector would have to choose between capturing one side or every side
of a link, which is the user's choice.

### The UI

The Links table on the Nodes tab gains a Capture button per link while the lab is live. Its
dialog offers the link's endpoints as checkboxes (the first one ticked, because both ends of a
point-to-point link see the same packets), a duration (default 30 seconds) and an optional packet
limit. It shows elapsed time and bytes received, and a Stop button that ends the capture early
and saves what arrived. Stopping before the first byte (the server answers in about 0.15s)
saves nothing, and closing the dialog drops the capture. A capture that runs its full course
does not download by itself: it waits for a Save file click, since browsers hold back or ask
about downloads nobody clicked for (Chrome blocks a page's second automatic one). Stop saves at
once, because that click is the user's.

The browser fetches the stream rather than following a download link, for two reasons: a
download link cannot show an error envelope (the browser just reports a failed download), and
it cannot stop early and keep the result. The cost is that the capture is held in memory until it
is saved. Stopping cuts the file at the last complete pcapng block, so Wireshark reads it
without a truncation warning. Very long or busy captures belong to the client library or `curl`,
which write to disk as the bytes arrive.

## Delta 37: `GET /labs/{name}/nodes/{node}/logs/stream`

```
GET /labs/{name}/nodes/{node}/logs/stream?tail=200
-> 200 text/event-stream
   event: log   data: {"stream": "stdout", "line": "..."}
   event: end   data: {}
   : keepalive
```

- **Permission: `lab:read`**, like the snapshot route.
- **Server-Sent Events**, like `/events`, so a browser opens it with `EventSource` and the
  proxy's existing handling applies (the backend sends `X-Accel-Buffering: no`). The stream
  starts with the last `tail` lines (0 to 10000, default 200, the snapshot route's default),
  then follows.
- **`log`** carries one line, verbatim (Docker's timestamp prefix included, as in the snapshot),
  and its `stream`, pinned to `stdout` or `stderr`. A container with a TTY (FRR's, for one)
  merges the two, so every line reads `stdout` there.
- **`end`** is sent when the upstream stream ends: the node was stopped (Docker stops
  following a stopped container, measured), the container was removed, or clab-api's 12-hour
  limit was reached. It tells a client to stop, because `EventSource` otherwise reconnects
  forever, and each reconnect would replay the tail.
- clab-api's blank keepalive becomes an SSE comment. That also makes a write reach a browser
  that left, which is how the backend notices and closes the upstream stream.

Errors before the stream starts: 409 `lab_not_running`, 404 `node_not_found`, 502
`upstream_error`.

**No replay on reconnect**, like `/events`: a client that reconnects asks for a tail again and
may see lines twice or miss some. The UI therefore does not reconnect on its own: on an error it
says the stream stopped and offers to follow again.

### The UI

The node logs dialog gains a Follow toggle, ON when the dialog opens (the maintainer's call
after review: the newest lines are what a log is opened for). Off, it is the snapshot with
Refresh. On, it opens the stream, appends lines in batches, keeps the newest 5,000, and scrolls with the output
unless the user has scrolled up. When the log ends or the stream drops it says which, and
offers to follow again. The dialog reads the stream with `fetch` and a small SSE parser
(`lib/sse.ts`), not `EventSource`: `EventSource` cannot read an error body, so a refusal (the
lab torn down while the dialog is open, the node gone, clab-api failing) read as a dropped
stream, and "follow again" could not fix it. A stopped node is not a refusal: its stream sends
the tail, then `end`.

## Both

- **Authorization is resolved up front, and its database session released before streaming**,
  the rule `/events` and the terminal already follow. These routes therefore do not use the
  `require_lab` dependency: FastAPI 0.139 closes a dependency's session only after the response
  has been sent, so a 30-minute capture would hold a pooled connection for 30 minutes. They
  answer 404 (existence hidden) and 403 exactly as `require_lab` does.
- **Only the lab's own node names go upstream.** Before opening a stream, the backend
  inspects the lab and refuses a node or capture target that is not one of its short node
  names (404 `node_not_found`, 422 `invalid_capture_target`), so a container name of another
  lab never reaches clab-api. clab-api refuses that too, even for Twinlab's superuser account
  (checked live), but the scoping is Twinlab's to enforce, as the snapshot logs route does.
- **Client** (`twinlab-client`): `capture(...)` yields the pcapng bytes as they arrive, and
  `follow_node_logs(...)` yields `NodeLogLine`s. Both are async generators, like `events()`, so
  a caller that stops early closes them with `contextlib.aclosing`.
- **MCP**: neither is a tool. A tool call returns one result, and a capture is binary.

## Deferred: resumable terminal sessions

clab-api can keep a terminal session running when its connection drops, and replay the output
the client missed when it reattaches (probed live: shell state survived, a second client took
the session over with close code 4001). It was deferred because Twinlab would have to own
something it does not today. Every session belongs to Twinlab's one clab-api account, so Twinlab
must record which of its users owns each session and re-check `lab:terminal` on every reattach.
And a detached session lives for 30 minutes against a limit of 128 sessions shared by all
Twinlab users.
