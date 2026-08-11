# The operator guide — plan and conventions

Working record for `docs/guide/`. Everything here is for people *writing* the
guide; none of it belongs in the guide itself, which is written for people
running Twinlab.

Opened 2026-08-11. ROADMAP item 25.

## Why

An audience survey found one row empty. The installer has the root README; the
API user has `twinlab_client_shape.py` and `client/README.md`; the maintainer
has the design records in `docs/`. The person who runs Twinlab through the web
UI has nothing — everything they need is written down, but as `why`-documents
for people changing the code.

The Build tab was the sharpest case: its settings were explained only by the
UI's own inline hints, which are reactive. They say why a control is greyed, not
what it does.

## Audience

Someone with a Linux host who needs a working lab, working mostly through the
web UI. Networking knowledge assumed; netlab and containerlab knowledge not.

Automating instead is a different audience with existing documentation. The
guide points at it and does not duplicate it.

## Writing rules

Binding for anyone adding to the guide. Settled 2026-08-11 by writing page 3
three ways and comparing the results.

### Content

- **Every setting names the key it writes.** A control does not exist on its
  own — it puts something in the definition. Say which. That is what makes a
  page useful to someone who later edits the YAML by hand.
- **Link netlab for protocol semantics; do not re-teach them.** Twinlab's job is
  to say what a control does to the definition. What OSPF areas mean is netlab's
  documentation, and behind that, the protocol's. Twinlab does not fork the
  documentation of 654 templates.
- **Verified, not remembered.** Every claim is checked against the code or a
  live stack before it ships. Design records are a starting point, not a
  source — some of them predate changes. Page 3 found three divergences this
  way, one of them an outright error in its own first draft.
- **Errors verbatim.** Quote the actual code slug and message. Made-up error
  text is worse than none, because it is unsearchable.
- **State the trap where it bites.** A handful of behaviours surprise people
  once — netem replaces rather than adds, `ssh -J` with `-i` fails at the hop, a
  lab name is capped at 16 characters. Each belongs on the page where someone
  meets it, not in a list of gotchas at the end.
- **No authoring material in the guide.** Rules, plans, status, source notes and
  work lists live here.

### Form

- **Second person, direct.** Say what to do, then what happens.
- **No buzzwords or marketing.** Not "powerful", "seamless", "leverage",
  "robust", "comprehensive". Avoiding these is the floor, not the target — page
  3's first draft had none of them and still had real problems.
- **Name the actor. No agentless passive.** Not "the key is refused" but "the
  builder refuses the key" or "the server refuses the key". This is the rule
  that pays for itself: **the builder**, **the server**, **netlab**, **Twinlab**
  and **clab-api** fail differently, and the passive hides which one you are
  talking to. Fixing 33 of these on page 3 added information, not just style.
  An adjectival participle is not passive and is fine ("the field is required").
- **One sentence, at most about 25 words.** Split at the second subordinate
  clause. Page 3's worst sentence was 55 words before this rule.
- **No semicolons.** Two sentences read better every time in a reference.
- **Lift a buried list out.** If a sentence carries three or more parallel
  items, make it a vertical list. Do not do this for two items.
- **Simple tenses.** "while you edited", not "while you were editing".
- **Em dashes stay.** They carry the asides that hold the *why*, and cutting
  them was the one clear loss when page 3 was rewritten without them. Use them
  for an aside, not as a general-purpose joint.

The tone target is the page-3 register: a reference someone reads under
pressure, with the reasoning kept in asides rather than removed.

## Keeping it true

The guide is in the repository so a behaviour change and its documentation ride
the same commit. Changing a control, a default, an error slug or a lifecycle
rule includes the page covering it.

## Status

| # | Page | State |
| --- | --- | --- |
| 1 | Install | **written** 2026-08-11 |
| 2 | Your first lab | **written** 2026-08-11 |
| 3 | The Build tab | **written** 2026-08-11 |
| 4 | Operating a lab | **written** 2026-08-11 |
| 5 | Test suites | **written** 2026-08-11 |
| 6 | Real configs in | **written** 2026-08-11 |
| 7 | Access | **written** 2026-08-11 |
| 8 | When something fails | **written** 2026-08-11 |
| 9 | Definition reference | **written** 2026-08-11 |

**All nine pages are written.** The outlines that lived here are gone — the
pages replaced them. What remains below is the material a future page or
revision still needs.

Page 3 is the reference for register and for the per-setting entry format. Read
it before writing another page.

`docs/guide/README.md` is held to the same rules — it is a page a reader sees.

Page 1 closed the node-image gap. The per-platform table there is now the only
place that says how to get all six images, so a platform admitted or withdrawn
in the future edits that table too. Add it to the checklist in
`docs/nos-sweep/admitting-a-platform.md` when you next touch that file.

Page 8's slug list came from a sweep of `ApiError(status, code, ...)` across
`api/` — 46 distinct slugs. Redo that sweep rather than trusting the page when
you add or rename an error.

Because the app serves the guide, **error codes could deep-link into it** —
page 8 is indexed by slug and its headings carry anchors, so a toast could
point at `/docs/troubleshooting#job_in_flight`. Not wired up; the anchors are
there when somebody wants it.

**No e2e coverage yet.** `/docs` is a new user-facing route and the browser
suite does not touch it. A `fast` spec asserting the index, one page's content
and a cross-page link would be cheap, and needs an e2e stack reset to verify.

## Decided

- **A docs site — SHIPPED 2026-08-11.** The app serves the guide at `/docs`,
  from `docs/guide/` itself: `frontend/src/content/guide` is a symlink to it,
  and compose mounts `./docs` at `/docs` so the symlink resolves in the
  container too. **The markdown has exactly one home**, so a page and the
  behaviour it documents still ride the same commit. Rendered with
  `react-markdown` + `remark-gfm` (both MIT, approved), styled from the app's
  own tokens, and reachable from the header nav and the command palette.

  Two decisions inside it. The route sits **outside the auth gate**, because
  the page you most need is the troubleshooting index and requiring a sign-in
  to read why you cannot sign in is backwards. And `<kbd>`, the guide's only
  raw HTML, renders as inline code rather than pulling in `rehype-raw` for
  sixteen occurrences on one page.
- **No screenshots** (2026-08-11). No page needs one, and images are the
  highest-maintenance part of a guide. If that changes, capture them by driving
  the real UI rather than by hand — a hand-taken screenshot goes wrong within a
  release and nobody can tell.
- **No prose checker** (2026-08-11). The rules above are the standard. They were
  derived with a tool's help and no longer need it, and a checker that scores
  prose invites chasing a number instead of reading the page.

## Planned: API documentation

Approved 2026-08-11. The guide covers the person clicking; nothing covers the
person automating, beyond two repository files (`docs/twinlab_client_shape.py`,
`client/README.md`) that a deployment does not serve.

### The reference already exists

**FastAPI generates it and nobody can reach it.** Probed on the running stack
2026-08-11: the backend serves a complete OpenAPI schema with **62 paths and
112 component schemas**, plus Swagger UI at `/docs` and ReDoc at `/redoc`. None
of it is reachable, because the backend port is not published and the frontend
proxies only `/api/v1`.

So the reference half of this is plumbing, not writing. Decide:

- **Which path.** The backend's own Swagger already lives at `/docs`, which is
  now the guide's path on the frontend. Different origins, so nothing is broken
  today, but pick deliberately before proxying — `/api-docs` or `/docs/api`.
- **Rendered by whom.** FastAPI's built-in Swagger and ReDoc cost nothing and
  look nothing like the app. Rendering the schema in-app matches the guide but
  is real work and probably another dependency.
- **Whether it needs auth.** The schema names every route. It reveals no data,
  and the guide sits outside the auth gate for a reason.

### What OpenAPI cannot say, and someone has to write

This is the part with actual value, and it mirrors what the guide does for the
UI. A schema lists routes. It does not teach the model:

- **The lifecycle**, and why deploy takes no definition — the single fact that
  makes redeploys reproducible.
- **Jobs.** 202 plus a job, one running job per lab, and the distinction
  between a refused submission and a failed job. Also which outcomes are
  deliberately successes (`config_failed`, `validation_failed`).
- **The error envelope** and its stable slugs. Page 8 already documents these
  for humans and the same list serves API callers.
- **Two credentials** — session cookie and `Authorization: Bearer` — and when
  an API key is the right one.
- **The SSE stream**: two named events, filtered to readable labs, no replay,
  so a consumer needs a fallback poll.
- **The terminal WebSocket** and its frame protocol.
- **Netem's REPLACE semantics**, which a schema renders as "some optional
  fields" and which is the most expensive misunderstanding in the API.
- **The Python client** as the recommended path, with `wait_job`.

### Shape

Most likely one more guide page — "Using the API" — carrying the concepts above
and linking to the generated reference, so the guide stays one thing. Same
writing rules. It would also replace the repository-facing pointer currently in
the guide's index.

## Deferred

- **In-app contextual help** driven by a shared field-help map, so the UI and
  the Build tab reference cannot drift. Real machinery; build it only if the
  reference proves hard to keep in sync.
