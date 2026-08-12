# The test-suite builder, and the loop it closes (contract delta 31)

Design record, 2026-08-11. Approved direction: a **visual builder for test suites**, plus the two
backend affordances it needs to be honest — landing **before the v1.0 tag**.

## The defect

Test suites are Twinlab's validation story. Authoring one is a `<textarea>`.

The whole surface is `SuitesEditor` in `frontend/src/components/lab/test-suites.tsx`: one dialog,
one CodeEditor, the **entire suite set** as JSON. Save does `JSON.parse` for syntax; everything
else — schema, matcher exclusivity, template rendering — is discovered at the PUT, or later.

That costs in three separate ways.

**The schema has rules a text editor cannot show you.** `expect` is exactly one of
contains/not_contains/matches/compare, and `compare` pairs with `parse` in both directions. Both
are `model_validator`s. Writing zero matchers, or two, or a `compare` with no `parse`, is a 422
you find after you have written the whole suite.

**The vocabulary is not in front of you.** `nodes` is a free-text list — a typo silently targets
nothing. A device-keyed `run` needs the netlab device slugs actually present in *this* lab. Fact
paths (`{{ nodes.pe1.loopback.ipv4 | address }}`) live behind a separate Facts dialog you read and
transcribe from. Every one of these is knowable from the lab's own definition; none of them is
offered.

**And the deepest one: you cannot see what the command returns.** The loop today is *write an
expectation blind → save → run → read the failure detail to learn what the output looks like →
edit → save → run again*. Two of those steps are a round trip through storage, and the
information you actually need — what this command prints on this node — arrives only as a
by-product of a failure.

For `compare` it is worse than slow. `compare` asserts over *parsed* data, so writing one means
predicting the shape TextFSM or `vtysh … json` will produce. `_run_check` computes that structure
and throws it away; nothing in the API has ever returned it. In practice a `compare` is written by
running something adjacent, guessing, and iterating against failures.

## The model

Three pieces, and they are deliberately different sizes.

### 1. The builder is total, because the schema is closed

The definition builder needed `lib/build-doc.ts` — typed core plus lossless extras passthrough, a
`parse(emit(doc)) == doc` invariant, a 90-check harness — because netlab owns that vocabulary and
it is open. Twinlab does not get to enumerate it.

**Test suites are Twinlab's own closed schema.** Every field is enumerable:

```
TestSuite     { stage: config-time|runtime, description, tests }
ValidationTest{ nodes[], run, wait, description }
TestCase      { command, expect, parse?, mode: shell|cli, interactive }
TestExpectation — exactly one of contains | not_contains | matches | compare
```

So the builder can be **total**: every valid suite is representable in the form, with no
passthrough machinery and no lossy-emit risk. Builder state *is* `Record<string, TestSuite>` — the
zod-parsed object the API already returns. The JSON view is `JSON.stringify` of that state and
coming back is `JSON.parse` + zod, so **switching modes is lossless in both directions**, which
Build's Visual/Text pair can never quite promise (comments, key order).

The one exception is `compare`: an arbitrary nested dict handed to napalm-validate. It gets an
embedded JSON sub-editor, and that is honest — it is data for another library's grammar, not
Twinlab's.

JSON stays the escape hatch, exactly as Text mode is for the definition.

### 2. Device capability becomes catalog data, not a second copy

Two questions the form must answer per device:

- may this case use `mode: cli`? — `CLI_ENTRIES` in `services/cli_adapters.py`, already exposed
  internally as `cli_capable(device)`, already the gate the suites PUT runs.
- may it use `parse: textfsm`? — `TEXTFSM_PLATFORMS` in `services/validation.py`.

Both are backend-only. A builder that greys these out by hardcoding a copy adds a **third device
table to the frontend** (`use-device-catalog.ts`'s static fallback is already one), and it drifts
silently the first time a platform is admitted.

So `CatalogDevice` gains two booleans, **derived** from those tables the way delta 22 derived
`config_import` from the importer's parser set:

```
cli_mode: bool   # `mode: cli` is meaningful here — the device has a CLI of its own
textfsm: bool    # `parse: textfsm` resolves a platform for this device
```

Derived, so they cannot drift; additive, so no consumer breaks. This is the whole backend change
the *form* needs.

### 3. The dry-run: one unsaved case, and what it actually printed

`POST /labs/{name}/test-suites/dry-run` — `lab:validate`, deployed lab, **synchronous**.

Request is one case and one node, with the expectation **optional**:

```
node: str                     # which node to probe
run:  { command, expect?, parse?, mode, interactive }
```

Response is what happened, including the part `_run_check` discards:

```
node, device          — who ran it, and what it is
command               — the RENDERED and ADAPTED command (what actually ran)
output                — captured stdout
parsed                — the parse result, when `parse` was set: the structure
                        a `compare` has to be written against
parse_error           — why parsing failed, with `output` still intact
status, detail, diff  — present only when an expectation was supplied
```

Everything is already a public function in `services/validation.py`: `render_template`,
`render_expectation`, `adapt_command`, `parse_output`, `evaluate_expectation`. The dry-run is a
recomposition of the same pipeline with two differences — it stops after `parse` when no
expectation is given, and it *returns* the parsed structure.

**Why synchronous.** Suite runs are 202 + a job because their worst case is the sum of every
test's `wait`. A dry-run has no `wait` (below), so it is one exec. More importantly the per-lab
job mutex means an async dry-run would 409 while any job holds it, and would itself block a
deploy — for an authoring aid, in a dialog. This is delta 24's reasoning exactly: batch runtime
actions stayed sync so runtime control survives a running job. A bounded timeout caps the cost.

**Why no `wait`.** `wait` is convergence polling for a real assertion — "this adjacency will come
up within 60s". An authoring probe asks a different question: *what does this print, now.* Polling
would only make a wrong command take a minute to say so.

**Why one node.** The 90% case is "does this work on r1". A node list would need a concurrency
policy the sequential suite runner does not have, and widening a scalar to a list later is
additive. The frontend offers a node selector defaulting to the test's first node.

**A parse failure is an answer, not an error.** In a saved run it is a `TestResult` with status
`error`, correctly — the assertion it fed can no longer be made. While authoring, it is the single
most useful thing the endpoint can say, so it comes back 200 with `parse_error` set and the raw
output intact. Seeing what the parser choked on is how the case gets fixed.

**It is not new capability.** `run_suite` already executes arbitrary commands on nodes under
`lab:validate`. This aims the same permission at a case that is not stored yet — which is the
entire point: today you must *save* a suite to learn whether it works.

## Delta 32: the target, and why a node list was the wrong one

Added 2026-08-11, once the builder made the shape visible.

`ValidationTest.nodes` was a required list of node names, and that is not
**edit-proof**. Add a router to the lab and every existing test keeps testing
the old set — silently. Nothing fails; the suite simply stops covering what it
was written to cover, which is the worst way for a check to be wrong.

So the target becomes three selectors, unioned:

```
all_nodes: bool          every node in the lab
groups:    list[str]     every member of these groups
nodes:     list[str]     exactly these
```

`all_nodes` is the edit-proof answer. `groups` is the *intent-preserving* one —
"every core router" stays true as the core grows, and the group is already
declared in the definition, so the suite reuses a fact about the topology
instead of restating it. `nodes` remains for the cases that really are about
one node.

They compose, which is the case the maintainer actually asked for: `groups:
[core], nodes: [x, y]` is "all of group core, plus x and y".

**Where the resolved membership comes from** — three sources, and the split
matters because the obvious answer was wrong.

*Membership* comes from the expanded topology: netlab has applied its own rules
by then, so that is authoritative. *The name set* comes from the definition,
because netlab's expanded `groups` also carries internal bookkeeping of its own
— a plain linux lab gets `netlab_no_collect` and `netlab_no_reload`, which must
never appear as test targets. *Flattening* is ours: netlab does **not** resolve
a nested group, and `core: [inner, n3]` stays exactly that in the output
(verified against netlab 26.07). The first draft of this design assumed netlab
flattened; it does not.

`ClabArtifacts` carries the result, the lab record caches it exactly like
`node_facts` (regenerable, lazily backfilled), and `GET /labs/{name}/facts`
serves it alongside the namespace, because a builder needs both at once: the
namespace to template against, the groups to target by.

**Order is first appearance** — `all_nodes` in topology order, then each group's
members, then the explicit nodes. That is not an arbitrary rule: it means a
test that selects only `nodes` runs in exactly the order it always did, so the
change is invisible to every suite that already exists.

`nodes` becoming optional is the only compatibility question, and it goes the
safe way: every stored suite still validates, because a non-empty `nodes` is
still a complete selector. What is now rejected is a test that selects
*nothing* — which the old `min_length=1` rejected too.

## What is deliberately not included

- **No `wait` on the dry-run**, per above.
- **No multi-node probe**, per above.
- **No suite-level dry-run.** Running a whole unsaved suite is `run_test_suite` with extra steps;
  the authoring loop is per-case.
- **No new permission.** Authoring is `lab:edit` (unchanged), probing is `lab:validate` — the
  same split the saved surfaces already use. A dry-run executes on nodes, so it is the suite-run
  class, not the authoring class.
- **No storage.** A dry-run writes nothing: not `last_validation`, not the config-time gate, not
  a job row. It is a question, not an operation.
- **No client-side Jinja.** Rendering is server-side and must stay the *same* engine — a JS
  reimplementation would render subtly differently, which is worse than not rendering at all. The
  dry-run is how the frontend learns what a template resolves to.
- ~~**Not a tab.**~~ **REVERSED 2026-08-11** — see "The Tests tab" below. The reasoning here
  ("suites are secondary") was about *authoring*, and authoring was never the whole job: reading
  a run is, and a card could not do that. Left in place rather than edited away, because the
  argument that lost is the reason the tab looks the way it does.
- **No device selector in the target** (delta 32). "Every VyOS node" is expressible already, and
  better: a device-keyed `run` skips the nodes whose device has no case, which is the same set
  with a per-device command attached. A second way to say it would only disagree with the first.
- **No negation or globbing** in the target. `all_nodes` minus one node, or `r*`, are both
  askable — but a suite that says which nodes it means is auditable, and a pattern that silently
  matches a new node is the edit-proofing problem in a new costume. Groups are the declared,
  reviewable way to say "this set, and keep it current".

## Gates

Backend: `ruff format` + `ruff check` + basedpyright strict + pytest, plus blackbox coverage
pinning the delta (catalog flags derived per device, dry-run gating, rendered command, parsed
structure, expectation outcome).

Frontend: `pnpm typecheck` + `pnpm build`, plus a `pnpm check:` harness over the pure suite-model
module — the `check:build-doc` pattern, since the frontend still has no test runner.

E2E: a new **fast** spec, since authoring is a PUT and needs no containers; journey 04 gains the
Try path against the live lab. (Both were reworked onto the Tests tab below — `fast/13` is now
`13-tests-tab.spec.ts`, 8 specs.)


## The Tests tab (2026-08-11)

Frontend-only — the wire is unchanged, and there is no delta. What changed is where suites live
and what shape they are read in.

### The defect, again

Delta 31 fixed *authoring* and left *reading* exactly as it was. After a run, the panel offered
one flat table of `(test, node)` rows — which is the shape the API serves, and the shape it
should serve, because that is what the pipeline produces. It is not the shape the question is
asked in. "Did OSPF converge?" is about a TEST; a test that ran on eight nodes arrived as eight
undifferentiated rows, and a suite of six tests over eight nodes as forty-eight of them, sorted
by nothing an operator was thinking about.

The test itself was worse off. What it targeted, what it ran, whether it was device-keyed —
none of that was visible anywhere except inside the editor, and the editor was one dialog for
the entire lab. So the dialog carried the navigation (a rail of every suite and every test) as
well as the work, and it was the only place any of the information lived.

### The shape

Three moves, and they are one idea: **the test is the unit.**

1. **`/labs/$name/tests` is a tab.** It is the navigation, so nothing else has to be.
2. **A test is a card** carrying its target, its command(s), its flags — and its last run folded
   onto it as one pill per node, each opening into the full result (the rendered+adapted command,
   the raw output, the compare diff). The output is the part the old table never showed, and it
   is usually the whole answer.
3. **The modal is one test.** Everything the rail used to do is on the page; what is left is the
   test you clicked. The suite's own three fields are their own small dialog, and the whole-map
   JSON is a third — still lossless both ways, for the same reason as before (the schema is
   closed).

Above the suites sits the lab's whole validation state, and a filter (**All / Problems / Not
run**) — because after a run, "what broke" is the only question, and before one, "what have I
not run yet" is.

### Three things that had to be decided, not assumed

**A create cannot save first.** The obvious flow — "New suite" writes a suite with a blank test,
then you edit it — is impossible: `TestCase.command` has `min_length=1`, so a blank test is a
422, and an empty suite is one too. Seeding a placeholder command would ship a test that passes
trivially, which is worse than no test. So a create does not save: the suite settings dialog
hands its three fields to the test editor, and **both are written on the same Save**. Cancel
leaves nothing behind. (The e2e suite found this — the first implementation PUT the blank and
the API refused it.)

**A roll-up needs an order, and `error` outranks `fail`.** A test's headline badge is its worst
node. Ranking error above fail is deliberate: a fail is an assertion that was made and came back
false — a finding about the network — while an error is one that could not be made at all, which
is the state you can conclude least from and the one most likely to mean the test is broken. The
tally line beside it always shows the full picture, so the ranking only decides the headline.

**Orphaned results are reported, not dropped.** Rename or delete a test and the last run still
holds rows naming it. Hiding them would be tidier and dishonest — they were about a test with
that name, once — so the suite says so in a line.

### Where the logic lives

`lib/test-results.ts` is pure and dependency-free: grouping, roll-up, tallies, the lab-wide
aggregate, the filter. It joins `lib/test-suite-model.ts` and `lib/fact-completions.ts` under
`pnpm check:test-suites`, which is now 48 checks. `lib/use-suite-authoring.ts` resolves the
lab's vocabulary (nodes, devices, groups, facts, catalog) once for the page, so a dialog opens
with it already in hand rather than starting a fetch.

`Run all` is the single verb in a loop, client-side. There is no batch endpoint and there should
not be one: the per-lab job mutex makes concurrency impossible anyway, and running them in turn
lets each suite's results land as it finishes.

### The reading pass (2026-08-12)

The tab shipped and then got looked at, in a browser, screenshot by screenshot. Six things it
got wrong, all of them about reading rather than authoring:

**The visual weight was inverted.** `pass` mapped to shadcn's `default` badge (a solid fill) and
`fail`/`error` to `destructive` (a pale tint), so a suite with nineteen passes and one failure
rendered as twenty amber blocks with the failure as the faintest thing in the row — the page
shouted about what was fine and whispered about what was broken. The whole grammar now lives in
`components/lab/tests/status-badge.tsx`: a pass is a quiet outline, a fail is outlined in red,
and `error` is the only solid fill on the page, which also makes the roll-up's ranking visible
instead of merely true. Every state carries an icon, so nothing is encoded in colour alone. The
stage badge stopped being a solid amber block for the same reason — it was competing with the
verdicts for the same colour, and a stage is context, not a verdict.

**A row of identical passes is not data.** Every card printed its tally and then a pill per node
each carrying an elapsed time nobody asked for. The pills lost the timing (it is on the opened
result, where someone is asking) and an all-passing run folds them behind the tally.

**A passing `compare` is fourteen lines of JSON saying so.** The diff now folds away on a pass
and stays open on anything else. The result header stopped repeating the pill that opened it and
leads with the REASON instead, which is the answer; command and output copy in one click.

**Descriptions ate the page.** Some run to nine lines at 1024px, which pushed the first test off
the screen. Clamped to two with an expander. And a suite contributing nothing to the current
filter used to render its full header, badges, description and Add-test button in order to say
"nothing here" — it is one line now.

**The actions wrapped.** `flex-wrap justify-between` on the test header dropped Edit and ⋯ under
a two-line description on some cards and left them top-right on others. They are a column of
their own now.

**The dialog buried the assertion.** One scrolling stack put Assertion below the fold and Try
below that, while the right half of the dialog sat empty. It is two columns at `lg`: what the
test IS on the left (name, wait, description, target), what it DOES on the right (case, command,
flags, Try, assertion). Try moved above the assertion inside `TestCaseEditor` — it runs with the
settings above it and its parsed output lands directly above the compare being written against
it, which is what the dry-run was for.

Deliberately NOT changed: the roll-up ranking `skip` above `pass`, so a test that passed on six
nodes and skipped one badges as `skip`. It hides the six passes and a skip is not a problem —
but changing it changes what a badge MEANS, so it is a decision, not a fix, and it is parked.
