# Widening config import, and the netlab dependency

Research record, 2026-08-11. Two questions asked together, and they turn out to
share an answer:

1. Can config import (deltas 22/23) support device types beyond VyOS and IOS?
2. Is Twinlab too dependent on netlab, and is there an alternative?

The short version: **import is cheap to widen and is the part of Twinlab that
depends on netlab least**; **netlab is not replaceable at any sane cost, but the
dependency is already narrower than it looks and can be bounded further.** The
two are connected — growing import grows the share of Twinlab's value that does
not rest on netlab's config templates.

---

## Part 1 — Widening config import

### What a platform actually costs

The parser contract is one function:

```python
parse_<platform>(content: str) -> Result[ParsedSource, ParseError]
```

`ParsedSource` is `hostname`, `interfaces`, `stanzas`, `warnings`
(`configimport/model.py`). Everything downstream of it — wiring validation,
the subnet-join suggestion, skeleton emission, the modeled/carried/quarantined
partition, the interface-map rewrite, the fidelity diff — is platform-agnostic
by construction, because the partition invariant is defined over stanzas rather
than over any platform's syntax.

Existing parsers: `vyos.py` 218 lines, `ios.py` 146 lines. That is the real
per-platform cost of the parser itself.

Around it, each platform also needs:

| Piece | Where | Size |
|---|---|---|
| Parser | new module | ~150–220 lines |
| Quarantine rule list | `classify.py` `_<PLAT>_RULES` | ~10–25 tuples |
| Modeled-address pattern | `classify.py` `_<plat>_address_re` | ~5 lines |
| Carry rewrite | `rewrite.py` `rewrite_<plat>` | ~40–100 lines |
| Dump command | `diff.py` `DUMP_COMMANDS` | 1 line |
| CLI adapter | `cli_adapters.py` (delta 28) | already present for admitted platforms |

### The refactor that has to come first

The dispatch is currently shaped for **exactly two** platforms — four binary
branches, not tables:

- `classify.py:123-125` — `is_vyos = device == "vyos"`, then `rules` and
  `address_re_for` chosen off it (plus behavioural branches at `:146` and `:162`)
- `pipeline.py:286` — `rewrite_vyos if source.device == "vyos" else rewrite_ios`
- `diff.py:48` — `parse_vyos(content) if device == "vyos" else parse_ios(content)`
- `diff.py:105` — the same rewriter ternary again

Only `_PARSERS` (`pipeline.py:50`) and `DUMP_COMMANDS` are already tables.

A third platform forces these into one per-platform record — call it
`PlatformImporter` — holding `{parse, quarantine_rules, address_pattern,
rewrite, dump_command, stanza_style}`. That is a contained refactor (roughly
half a day including tests) and it is a prerequisite, not optional: the `else`
branches currently mean "IOS", so adding FRR without the refactor would silently
route FRR through the IOS rules.

### Two structural families, and both already exist

The one genuine semantic axis in `classify.py` is how a stanza carries its
identity:

- **Flat command set** — VyOS `set interfaces ethernet eth0 address …`. Lines are
  independent commands; there is no header line; the stanza key is a path prefix.
  Consuming a modeled address just drops that line.
- **Hierarchical with header** — IOS `interface Gi0/0` followed by indented
  children. `classify.py:154` already handles this: the header is carried while
  any child survives and modeled when the whole stanza is consumed.

This matters because the two admitted-but-unimportable platforms map cleanly
onto the existing machinery:

- **FRR** — `vtysh -c "show running-config"` is IOS-flavoured hierarchical text.
  It reuses the header/children logic and much of the IOS interface-name
  handling (though FRR names are Linux names, `eth0`/`swp1`, so the abbreviation
  table shrinks rather than grows).
- **RouterOS 7** — `/export` is flat, path-prefixed, closer to VyOS. Its one new
  wrinkle is line continuations (a trailing `\`), which normalize away before
  parsing.

So neither needs a new family; both are instances of one that is already
written and tested.

### Recommended order

**1. FRR first.** It is an admitted platform, so import → deploy → config-diff
works end to end — unlike IOS, where the withdrawal on licensing means an
imported lab is promised nothing. Its config shape reuses the hierarchical
machinery. And FRR is what a great deal of white-box and cloud-router estate
actually runs, so real dumps are easy to come by.

**2. RouterOS 7 second.** Also admitted, flat family, and it is the platform most
likely to appear in a real customer edge that someone wants twinned.

**3. Nothing else, without a decision.** Every further platform (Arista EOS,
NX-OS, Junos) is *not* an admitted platform, so importing one yields a definition
Twinlab cannot deploy — the exact position IOS is in today. Widening the parser
set past the deployable set produces labs that look importable and then aren't.

### Explicitly ruled out: cross-platform import

"Parse an Arista config, emit an FRR node" is not a smaller version of this
feature — it is a different product. The carry mechanism is *verbatim source
config* replayed onto the same NOS; it cannot cross platforms. Making it cross
platforms means config translation, which is an open research problem and would
destroy the property that makes import trustworthy today: every source line is
either modeled, carried verbatim, or visibly quarantined.

### Worth considering: structure-only import as a separate tier

There is a legitimate cheaper tier that would cover many platforms at once.
Parsing *hostname + interfaces + addresses* is easy and nearly platform-neutral;
parsing the full stanza structure for faithful carry is what costs 200 lines and
platform expertise.

A **structure-only import** would model the topology and quarantine everything
else — you get the shape of the production network as a deployable lab, with no
protocol config. The three-bucket invariant still holds; the carry bucket is
simply empty. That is honest, useful ("recreate my topology in a lab"), and it
would let a single generic parser cover platforms Twinlab will never carry.

It is a product decision, not an engineering one: it trades the fidelity promise
that currently distinguishes Twinlab's import for breadth. Recorded here as an
option, not a recommendation.

### Batfish, evaluated and not recommended

Batfish (Apache-2.0) parses Cisco/Arista/Juniper/Cumulus/FRR/SONiC configs into
a vendor-neutral model, which sounds like it would deliver every platform at
once. It should not be adopted here:

- It **models**, it does not **partition**. Twinlab's carry needs every source
  line placed verbatim into exactly one bucket; Batfish gives a semantic model
  from which the original text cannot be reconstructed. The completeness
  invariant — the thing that makes import auditable — would be lost.
- It is a JVM service, a substantial new runtime dependency in the stack for a
  feature that is currently pure Python.

It remains interesting for a *different* feature (pre-import analysis of a
config estate), and the license is clean, so it is not disqualified — just not
the answer to this question.

---

## Part 2 — The netlab dependency

### What netlab actually is, measured

Inside the runner image, netlab 26.07 is:

- **43,700 lines** of Python
- **654 Jinja config templates**
- **40 device definitions**, **21 protocol module directories** (bgp, ospf,
  isis, mpls, vrf, vxlan, evpn, srv6, lag, stp, …)

Per admitted platform, the config-template counts are: linux 42, frr 36,
vyos 27, routeros7 15, bird 4, dnsmasq 1.

### The dependency is four separable services, not one

| | Service | Twinlab's exposure | Replacement cost |
|---|---|---|---|
| **A** | Topology expansion, IPAM, per-device interface naming | `create_clab_topology() → ClabArtifacts` — **one function, one return type** | Weeks–months. Real, bounded, testable. |
| **B** | Device data (clab kind, default image, kmods, connection) | Already mirrored into `device_catalog.py` / `DEVICE_KMODS`, with drift-guard tests | Near zero — it is already ours |
| **C** | **Multi-vendor config generation** (654 templates × 21 modules) | `netlab initial` in the runner | **Not viable.** See below. |
| **D** | Config-push orchestration (Ansible inventory + playbooks per transport) | runner `/configure` | Weeks (Nornir/scrapli), at the cost of multi-transport coverage |

Twinlab has *already* taken back everything it reasonably could. It never runs
`netlab up`; deploy goes to clab-api, host preparation to the hostprep sidecar,
impairment to the netem API, validation to Twinlab's own test suites, image pins
to an injected `topology-defaults.yml`. What remains is A and C, and C is the
whole ballgame.

### Why C cannot be replaced

The value proposition "write `module: [ospf]` and get correct OSPF on six
different NOSes" *is* those 654 templates. Reimplementing even a narrow slice —
6 devices × 5 modules — is a large corpus that would be permanently behind
upstream, and its failure mode is the worst kind: a protocol that silently does
not converge, discovered by a user rather than a test. netlab has years of
per-device quirk knowledge encoded in it that is invisible until you lack it.

Nothing else open source occupies this niche:

- **containerlab** is the layer *below* — Twinlab already uses it via clab-api.
  No IPAM, no config generation. Not an alternative; a component.
- **Kathará** sits at the same layer as containerlab, is GPL, and also has no
  multi-vendor config generation.
- **GNS3 / EVE-NG** are GUI-first, VM-centric, GPL — wrong shape entirely.
- **Nornir / Scrapli / NAPALM** replace D and would let Twinlab own C. "Own C"
  is precisely what it cannot afford.

**Conclusion: there is no alternative to netlab that preserves what Twinlab
sells.** The dependency is a deliberate division of labour, not an accident.
Twinlab's differentiator is everything around it — lifecycle, RBAC, async jobs,
the visual builder, config import, validation, the API and client.

### The real lock-in is the language, not the binary

Swapping engines is not blocked by the subprocess call. It is blocked by the
fact that **the stored definition is netlab YAML**, and that language is load-
bearing across:

- every stored lab definition and the `examples/`
- the builder's `parseBuildDoc` / `emitBuildDoc` and its whole typed core
- the template library's content (both tiers)
- the public API contract and the published client
- delta 26, which **promises netlab's expanded-node shape to users** as the fact
  namespace's contract tier

That last one is the sharpest edge: Twinlab has made a public promise about
netlab's internal data shape. It was the right call (the alternative was
promising nothing), and `_extras` correctly fences off the unpromised part — but
it means an engine swap is an API break, not an implementation detail.

One thing already cuts the other way, and is worth naming: **the builder's typed
core is a de facto Twinlab-owned schema.** It covers all three examples, it has a
round-trip invariant, and it is guarded by `pnpm check:build-doc`. If a schema of
Twinlab's own ever became necessary, it already exists in draft.

### Recommended mitigations, in cost/benefit order

**1. Pin harder. (minutes)** `networklab>=26.7` in both `pyproject.toml` files
would float on an unlocked resolve. The lock files hash-pin 26.7 and both
Dockerfiles use `uv sync --frozen`, so shipped images are reproducible today —
but the pyproject should say `==26.7` so the floor and the actual are the same
number, and an upgrade is an explicit edit.

**2. Golden-file the seam. (about a day — highest value)** Today's drift guards
cover kmods, catalog module support, default images, fact-namespace shape and
the packaged network templates. What is *not* guarded is the thing that actually
matters: the **emitted clab topology and expanded JSON** for the three examples.
A test that runs `netlab create` on each example and diffs against a checked-in
snapshot turns every netlab upgrade into a reviewable diff instead of a live
surprise — and, not incidentally, is exactly the test suite an engine
replacement would have to pass. This is the single best hedge available.

**3. Keep the two seams narrow. (policy)** `create_clab_topology() →
ClabArtifacts` and the runner's `/configure` are the only two places netlab is
reached. They already are; the rule is simply that nothing new may read netlab
directly, and mirrored data (`DEVICE_KMODS`, `IMAGE_PINS`, catalog module
support) must stay drift-guarded.

**4. Understand the actual risk, which is not abandonment.** netlab is MIT and
hash-pinned. The realistic bad day is not "netlab disappears" but "netlab ships
a breaking change we cannot absorb" — and against that, MIT plus a pin means
staying on 26.07 indefinitely and vendoring a patch is a legitimate, cheap
option. That is a materially better position than the same dependency on
anything proprietary. The bus-factor concern is real but it is *manageable*, and
managing it costs the two items above rather than a rewrite.

### The strategic connection

An imported lab's definition carries **no `module:` key at all** (`emit.py:92`).
netlab generates its interface addressing and hostname — the implicit `initial`
module — and every protocol line rides the carry verbatim. Verified by reading
the emitter: the skeleton is `{provider, nodes, links}` and nothing else.

So the import path already runs on service **A** alone, with none of C. Every
platform added to import extends Twinlab's reach without adding a single
netlab-template dependency — and it does so in the direction of the use case
that is hardest for netlab-native tooling to serve, because a real production
config is exactly what a declarative module system cannot express.

That makes widening import both the cheaper feature *and* the one that reduces
the concentration of value in netlab's templates. It is the same work either way.

---

## Suggested sequence

All of this is post-v1.0 — none of it belongs in front of the release train.

1. Pin `networklab==26.7` in both pyprojects (minutes)
2. Golden-file the `netlab create` seam for the three examples (~a day)
3. `PlatformImporter` refactor — four binary branches into one table (~half a day)
4. FRR import parser + rules + rewrite (~2–3 days including a live diff proof)
5. RouterOS 7 import parser (~2–3 days)

Steps 1–2 are the netlab hedge and stand alone. Step 3 is a prerequisite for 4
and 5. Nothing here requires a decision about replacing netlab, because that
decision should be **no** — the question worth revisiting periodically is
whether the seam is still narrow, and step 2 is what makes that answerable.
