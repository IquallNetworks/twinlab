# Job steps: what the operation actually did (contract delta 29)

Design record, 2026-08-10. Approved direction: a **server-side step log on the job record**,
landing **before the v1.0 tag** (so the contract the tag freezes already carries it).

## The defect

A running job is visible; what it is *doing* is not.

- The deploy dialog streams progress, but only while it is open, and only from the session's SSE
  ring buffer (`frontend/src/lib/lab-event-store.ts`). Closing it does not lose the events — the
  store is module-scope — but no other surface renders them per-lab, so they become unreachable.
- The job detail sheet, the surface a user naturally clicks, shows the row: kind, status, timing,
  and the `request`/`result`/`error` JSON. Nothing about the run.
- Neither survives a page reload, and neither exists at all for a job that ran while no browser
  had the stream open. The backend opens **one upstream clab-api stream per browser connection**
  (`api/events.py`) — with nobody watching, nothing is recorded anywhere.

And the deepest part: **container events were never the interesting information.** The phases that
decide whether a deploy is healthy — the image pre-flight, host preparation, netlab's own output,
Ansible's per-node config push, the config-time suites — run inside `_deploy_job` and never leave
the backend. That is the "quiet stretch" the deploy dialog currently apologises for in prose:

> The config push and netlab's own output do not stream — a quiet stretch after the nodes appear
> is normal.

An apology for missing information is the tell that the information should exist.

## The model

A job row grows a `steps` list. Each step is what the operation did, recorded as it happened:

```
JobStep:
  at       — server timestamp of the append
  code     — a PINNED slug naming the phase (see the vocabulary below)
  level    — info | warning | error
  message  — one human-readable line, with the numbers that matter
```

`code` is pinned rather than free text for the same reason error codes are: a client can branch on
it and the black-box suite can assert it. `message` carries the detail no vocabulary can
anticipate ("7/7 nodes ok", "image X not present locally"). The pair is the same split as the
error envelope's `code`/`message`.

**Steps are a narrative, not a result.** The terminal payload stays on `result`/`error`, typed by
kind, and nothing may be derivable ONLY from a step — a client that ignores steps entirely must
lose nothing but readability. That keeps them free to gain entries without a contract change.

### Vocabulary

**deploy**

| code | level | when |
| --- | --- | --- |
| `host_resources` | info | what the host had left when the deploy began (delta 30) |
| `topology_generated` | info | `netlab create` returned — node and link counts |
| `image_preflight` | info / warning | all images present, or which are missing-but-pullable |
| `host_prep` | info | bridges created and kernel modules loaded (omitted when the lab needs none) |
| `clab_deploy_started` | info | handing the topology to clab-api — the first long wait |
| `nodes_deployed` | info | containers up, with the count |
| `nodes_ready` | info | every node's NOS answered (`netlab initial --ready`) |
| `config_push_started` | info | Ansible begins — the second long wait, and the quiet stretch |
| `config_pushed` | info / error | per-node outcome, `N/M nodes ok` |
| `validation` | info / error | config-time suites, `N/M passed` |

**configure** — `config_push_started`, `config_pushed`, `validation`.

**destroy** — `clab_destroy`, `bridges_released`, `files_removed`, `record_removed`.

**suite_run** — `suite_started` (tests × nodes), `suite_finished` (`N/M passed`).

A `_started` code exists only where the phase is long enough that its absence reads as a stall.
Fast phases get one step, at their outcome.

## Decisions

**Stored as a JSONB column on `jobs`, not a table of its own.** Steps are ≤ a dozen per job, always
read with the job, never queried across jobs, and die with it. That is exactly the shape of
`request`/`result`/`error`, three decisions already made this way in this table. Migration 0021
adds `steps JSONB NOT NULL DEFAULT '[]'` — jobs predating the column read as `[]`, which is honest:
they have no steps, and nothing can invent them.

**Appended with an atomic `steps = steps || <step>`, in the recorder's OWN session.** Not
read-modify-write: the job task holds a long-lived session mid-operation, and a step must be
committed and visible to a poller the moment it happens, without interfering with whatever
transaction the operation is in the middle of.

**The recorder does not swallow its own failures.** A step write is an `UPDATE` on a row the task
owns; if it fails, the database is gone, and the operation writes lab status throughout and would
fail at the next store call anyway. `run_job`'s total `except` turns it into a failed job — the
same treatment every other store call in a job already gets. The backend has no logger, so
catching here would mean discarding the failure silently, which is worse than failing loudly.

**Capped at 64 steps**, after which one `steps_truncated` step is recorded and appends stop.
Nothing emits more than ~10 today; the cap is there so a future loop cannot bloat the row.

**Served on the single-job GET only** — `GET /labs/{name}/jobs/{id}` returns a new `JobDetail`
(`Job` + `steps`), while `GET /labs/{name}/jobs` and `GET /jobs` keep serving `Job`. The lists
render kind/status/timing and would otherwise carry ~2 KB of narrative per row, ~100 KB for the
dashboard's `limit=50` poll, for nothing. This is the same summary/detail split `LabSummary` and
`LabDetail` already make.

**No new SSE event.** Delta 16 pinned `job` events as a poke — "never the result/error, which stay
on the record" — and steps are on the record. The drawer polls the single-job endpoint while the
job is running, which is what `waitJob` already does. Streaming steps would mean a third named
event carrying durable data over a deliberately LOSSY broker; if it is ever wanted, it is additive
and can be added then.

**The job's work gains the recorder as a parameter**, so `JobWork` becomes
`Callable[[JobStepRecorder], Awaitable[BaseModel]]` and `spawn_job` binds one per job. The job id
lives in `api/jobs.py` and never reached the operation bodies before; passing the recorder gives
them the one capability they need without handing them the row.

## What the frontend does with it

The job detail sheet gains a **Steps timeline** — durable, so it reads the same during the run,
after it finishes, and next week. While the job is `running` it also renders the session's live
container events for that lab beneath, labelled as this-session-only, since those still arrive
faster and finer-grained than a poll.

Attributing container events to a job needs no correlation id: the **per-lab job mutex** means at
most one job owns a lab at a time, so "that lab's events between `created_at` and
`finished_at ?? now`" is exact, not a heuristic.

The deploy dialog renders the same component, which is what finally lets its prose apology be
deleted — the quiet stretch becomes `config_push_started`.

## Deliberately not in this delta

- **Capturing container events server-side per job.** It would make the per-node churn durable too,
  and would replace N upstream clab-api streams with one — but it is an SSE fan-out refactor with
  restart and duplicate-event handling of its own, and the step log is what answers the complaint.
  Considered and parked, not rejected.
- **Streaming netlab's and Ansible's raw output.** A step says the config push is running and how
  it ended; it is not a transcript. Piping subprocess output through the job record is a different
  feature with its own size and retention questions.
- **Steps as an audit log.** Jobs are pruned to `KEEP_FINISHED = 20` per lab; their steps go with
  them. Nothing here changes that, and nothing should treat a step as a durable record of fact.
