# Owning the lab definition

Design analysis, 2026-08-11. Follows `import-platforms-and-netlab-dependency.md`,
which measured the netlab dependency and concluded it should be bounded rather
than replaced. The concern this file answers is narrower and sharper:

> We do not own the laboratory definition in such a way that we could swap
> netlab in the future, or extend it.

That is two different concerns wearing one sentence, and they have different
answers. **Extending is solvable today and cheaply — the mechanism is already
proven and Twinlab already uses it once.** **Swapping is not bought by owning
the schema at all**, which is the part most worth being clear about, because
the two are easy to conflate.

---

## 1. Where we actually stand

The stored definition is netlab YAML. But it is already **not** plain netlab
YAML — it is a dialect Twinlab defines by exclusion:

- **minus** the directives the PUT rejects with 422 `unsupported_directive`:
  `tools:`, `defaults.netlab.up/down`, OVS `bridge_type`, link/interface `tc:`
- **plus** the record-owned pins the PUT writes in: top-level `name:`,
  `addressing.mgmt.ipv4`, `addressing.mgmt._network`
- **normalized** — the PUT re-dumps the YAML, which is why comment and
  formatting edits vanish from the drift comparison

So Twinlab already owns a language. It just owns it *implicitly*, defined by
what `find_unsupported_directives` happens to reject and what the PUT happens to
pin, spread across code and CLAUDE.md prose rather than written down as a
contract.

And there is a second, louder piece of evidence that the current arrangement
already constrains design: **every Twinlab-native concept lives outside the
definition, in a side resource, because the definition could not hold it.**

| Concept | Where it lives | Why not in the definition |
|---|---|---|
| Canvas positions (delta 19) | `GET/PUT /labs/{name}/layout` | presentation, and netlab validates the definition |
| Group colours (delta 20) | the same layout resource | same reason, stated explicitly in the delta |
| Test suites (delta 17) | lab record, "never sent to `netlab create`" | netlab has no such concept |
| Custom-config templates (delta 27) | lab record, materialized at the boundary | the fileset is netlab-facing, the *records* are not |
| Import provenance | **nowhere — it is lost** | no key to put it in |
| Impairment (gap 1) | netem API only; `tc:` is *rejected* | Twinlab owns the concern differently than netlab does |

The last two are the ones that hurt. A lab imported from production forgets
which source config each node came from — the diff has to recompute the join
statelessly every time, which is elegant but is a workaround for having nowhere
to write it down. And `tc:` had to be **rejected**, a legal netlab key refused
because Twinlab models impairment as live qdisc state instead. That is exactly
the shape of "we cannot extend the language": the disagreement could only be
expressed as a refusal.

## 2. What was actually probed (netlab 26.07, this stack)

Three probes, all run through the real runner:

**Unknown top-level key — hard rejection:**

```
IncorrectAttr in topology: Invalid topology attribute 'twinlab' found in topology
Fatal error in netlab: Cannot proceed beyond this point due to errors, exiting
```

**Underscore-prefixed key — accepted, and it survives into the expanded
topology.** At all three levels:

```
top-level : {'schema': 1}
node h1   : {'imported_from': 'r1.example.net'}
link      : {'sla': 'gold'}
```

This is not a discovery so much as a confirmation: `_`-prefix is netlab's own
convention for bookkeeping it carries but does not interpret, Twinlab already
depends on it for `addressing.mgmt._network`, and delta 26 already describes
"netlab's internal `_`-prefixed bookkeeping" as a thing that exists.

**So the definition is extensible in place, today, with no envelope and no
schema of our own.** A `_twinlab:` block at topology, node or link level rides
through `netlab create` untouched and comes back out the other side.

## 3. Extending: the recommendation

Adopt `_twinlab:` as **the** reserved extension namespace, with policy:

- **One reserved key**, `_twinlab`, at any level netlab expands (topology, node,
  link — all three verified). Never a second one, never a bare name.
- **A guard test.** `_`-prefix tolerance is a convention, not a documented API.
  A test that round-trips a `_twinlab` block through a real `netlab create` and
  asserts it survives turns a netlab upgrade that tightens validation into a red
  test instead of a production surprise. This is the whole cost of the mechanism.
- **It is Twinlab data, not user data.** Users author through the builder and
  text mode; `_twinlab` is written by Twinlab for Twinlab. It should be stripped
  by `strip_record_pins` where lab-specific (the template library serves
  definitions for *other* labs to instantiate), which is a decision per key, not
  a blanket one.
- **Side resources do not all move.** Layout is genuinely presentation and
  genuinely per-viewer-independent; it is right where it is. What belongs in
  `_twinlab` is what is *about the topology* and currently has nowhere to live:
  import provenance first, since it is being actively lost.

Note the pleasant consequence: because the block survives into the expanded
topology, node-level `_twinlab` lands in the fact namespace's `_extras` (delta
26's partition puts every unpromised key there), so a test suite could render
`{{ node._extras._twinlab.imported_from }}` with no new plumbing. Unpromised, by
construction — which is the correct tier for it.

**This does not require deciding anything about swapping netlab.** It is
additive, reversible, and costs one test.

## 4. Swapping: the part worth being clear about

**Owning the schema would not free Twinlab from netlab.**

Suppose the stored artifact became a Twinlab document tomorrow, compiled to
netlab YAML at the boundary — the builder's typed core (`build-doc.ts`) is
already a working draft of exactly that schema, with a round-trip invariant and
its own regression gate. What would that buy?

- **Extensibility** — already available via `_twinlab`, for one test.
- **Portability** — a real gain: one artifact instead of five resources.
- **Independence from netlab** — *no*.

Because the thing a definition means is "deploy these nodes with this config,"
and the part Twinlab cannot do itself is the config: 654 Jinja templates across
40 devices and 21 protocol modules. A Twinlab schema still has to say
`module: [ospf]`, and something still has to turn that into VyOS, FRR and
RouterOS configuration. Swapping the language changes the spelling of the
question, not who answers it.

Worse, the escape hatch leaks the dependency by design. `build-doc.ts` carries
extras verbatim precisely so netlab's full vocabulary stays reachable — so a
Twinlab-schema definition would contain netlab YAML in its extras, and the
coupling would survive the abstraction.

### What would actually buy optionality

Not a schema. **A conformance suite.**

Engine independence is a property you can only claim if you can *test* a
candidate engine. Today there is no artifact that says what "correct" output
looks like — the drift guards cover kmods, catalog module support, default
images, the fact-namespace shape and the packaged templates, but not the thing
that matters: the topology netlab actually emits.

A golden-file suite — run `netlab create` on each example, snapshot `clab.yml`
and the expanded JSON, diff on every run — does three jobs at once:

1. turns any netlab upgrade into a reviewable diff instead of a live surprise
2. is the exact suite a replacement engine would have to pass
3. makes *evaluating* an alternative a weekend, not a rewrite

That is roughly a day's work and it is the single highest-value thing available
on this whole topic. It was already the top recommendation of the dependency
analysis; the ownership concern is a second, independent reason for it.

### And the realistic risk is smaller than it feels

netlab is MIT and hash-pinned in both lock files, with `uv sync --frozen` in
both Dockerfiles. The bad day is not "netlab disappears" — it is "netlab ships a
change we cannot absorb," against which staying on 26.07 and vendoring a patch
is legitimate and cheap. The one loose end is cosmetic but worth closing: both
`pyproject.toml` files say `networklab>=26.7`, so an unlocked resolve would
float. Make the floor equal the actual.

## 5. Recommendation, staged

**Now — cheap, and neither commits to anything:**

1. Pin `networklab==26.7` in both pyprojects (minutes).
2. Golden-file the `netlab create` seam for the three examples (~a day). Buys
   upgrade safety *and* the ability to evaluate any alternative.
3. Write the dialect down — what Twinlab accepts, rejects and pins — as a spec
   rather than as behaviour spread across `find_unsupported_directives`, the PUT
   and CLAUDE.md prose. This is documentation of what already exists, and it is
   the precondition for both extending and swapping.

**Next — unlocks extension, low risk:**

4. Adopt `_twinlab:` with its guard test, and give import provenance a home in
   it. That closes the one place data is being actively lost.

**Only if forced — and not for the reason it looks like:**

5. Promoting `build-doc.ts`'s typed core to the authoritative schema is a real
   option and it is already half-built. Do it for **portability** — one
   exportable lab artifact instead of five resources — if and when that becomes
   a product requirement. Do not do it for independence from netlab, which it
   does not deliver.

**Explicitly not recommended:** replacing netlab. Nothing else open source
generates multi-vendor device configuration from a declarative topology, and
that capability is the product. The division of labour is correct; what was
missing is the test that keeps the seam honest.
