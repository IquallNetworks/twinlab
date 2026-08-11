# Adding a config-import platform — the checklist

Config import (deltas 22/23) turns a dump of a production device's running
config into a lab node. Supporting a new source platform is a **parser plus
three table entries** — it does not touch netlab, the deploy path, or the
definition schema, because an imported lab carries no protocol modules at all
(`emit.py`: the skeleton is `{provider, nodes, links}` and nothing else).

That makes this a much smaller job than *admitting* a platform
(`nos-sweep/admitting-a-platform.md`), which is about running a NOS. The two are
independent axes and must not be confused:

|  | can be **deployed** | can be **imported** |
|---|---|---|
| vyos | yes | yes |
| frr, routeros7, linux, bird, dnsmasq | yes | **no** |
| iol | withdrawn (licensing) | yes |

**Only the intersection is a complete story.** VyOS is the sole platform today
where import → deploy → config-diff works end to end. Adding an importer for a
platform Twinlab cannot deploy produces a definition that looks importable and
then isn't — which is exactly IOL's position, and is a product decision, not a
default.

---

## 0. Prerequisites

The platform must already be **admitted** (in `SUPPORTED_DEVICES`), or you must
be deliberately accepting the IOL situation. Check this first; it is the only
question here that is not an engineering one.

You need **two real config dumps**, not hand-written samples:

- one **source** dump from the production-style device you want to twin
- one **running** dump from a deployed lab node of the same platform, for the
  fidelity diff to compare against

Synthetic fixtures will pass tests and fail on the first real config. Every trap
below was found with real dumps.

## 1. Decide the stanza form

The single structural question, and it decides how much you write.
`ClassifySpec.stanza_form`:

- **`"flat"`** — every line is an independent command carrying its full path
  (VyOS `set interfaces ethernet eth0 address 10.0.0.1/30`, RouterOS
  `/interface ethernet set …`). Consuming the modeled address just drops that
  line; there is no header to keep.
- **`"block"`** — an indented body under a header line (IOS `interface Gi0/0`,
  FRR's vtysh output). The header is carried while any child survives and
  modeled when the address was the stanza's only content.

Both are implemented and tested. If a platform is neither, stop and think — you
are about to add a third form, which is a real change to `split_buckets` rather
than a table entry.

## 2. Write the parser

One function, in a new module named for the platform:

```python
parse_<platform>(content: str) -> Result[ParsedSource, ParseError]
```

`ParsedSource` is `hostname`, `interfaces`, `stanzas`, `warnings`
(`configimport/model.py`). For reference, `vyos.py` is 218 lines and `ios.py`
is 146.

**The invariant that matters:** every normalized source line must live in
exactly one stanza. The modeled/carried/quarantined partition is asserted at the
classify layer and it can only hold if the parser loses nothing. Decide up front
what "normalized" means for this platform and write it in the module docstring —
VyOS normalizes both dump formats to the flat `set` form and states plainly that
brace-format comments are the one thing that does not survive.

Interface facts (`SourceInterface`) are only for types the lab can realize.
Anything else — bonds, bridges, tunnels, VLAN subinterfaces — must be **absent
from `interfaces` and present as a warning**, so its config rides the carry
instead of inventing a link that cannot exist.

## 3. Write the ClassifySpec

Beside the existing ones in `classify.py`, not in the parser module: the four
quarantine classes are pinned contract and `auth` has to mean the same thing on
every platform, which is only auditable if the rule lists sit side by side.

- **`quarantine_rules`** — `(class, stanza-key prefix)` pairs. Classes are
  `mgmt` / `auth` / `telemetry` / `hardware`, pinned. The lists are code and may
  grow.
- **`address_pattern`** — the regex matching the ONE line the skeleton models
  for an interface. Get the spelling exactly right: IOS writes a dotted mask, so
  the pattern converts the CIDR; a near-miss silently double-writes the address
  into both the skeleton and the carry.
- **`mgmt_rule`** — only if the platform expresses management scope
  *structurally* beyond interface VRF membership (IOS mgmt-VRF routes and `vrf
  definition` blocks). Leave `None` otherwise.

**Never quarantine routing policy, ACLs, QoS or non-mgmt VRFs.** They carry and
apply — quarantining them silently guts the twin.

## 4. Write the rewriter

```python
rewrite_<platform>(lines, mapping, node) -> (rewritten_lines, notes)
```

Rewrites source interface names onto the netlab-assigned ones. Two rules learned
the hard way:

- **Single pass.** A replacement's output must never be re-matched, or a shifted
  map (`eth1→eth2`, `eth2→eth3`) cascades. IOS does this with one alternation
  regex; VyOS does it with one pass over the tokens.
- **Every unmapped interface-looking token becomes a `Note`.** Never silent.

If the platform has canonical abbreviations in show output (IOS `Gi0/1` for
`GigabitEthernet0/1`), the rewriter must handle every spelling — otherwise the
carry keeps references the lab has never heard of.

## 5. Add the table entry

One entry in `platforms.py` `PLATFORMS`, with the running-config dump command in
the **device's own CLI** (`cli_adapters` adapts it at the transport boundary,
delta 28 — do not pre-wrap it). `DUMP_COMMANDS` and the catalog's
`config_import` flag both derive from the table; nothing else to edit.

## 6. Tests

- Parser unit tests over the **real** dump, including both dump formats if the
  platform has two.
- A **partition test**: modeled + carried + quarantined reproduces the source.
  This is the one test that must exist.
- A pipeline test through `import_network` — it runs the real dry `netlab
  create`, so it catches an emitted skeleton netlab rejects.
- A diff test with the real running dump.

## 7. Verification gate

- `ruff format` + `ruff check` + `basedpyright` + `pytest` green in `backend/`
- **A live proof**, which is the whole point: import the real config, deploy the
  lab, run `POST /labs/{name}/config-diff`, and read the `missing` list. It will
  not be empty on the first try — every entry is either a rewriter gap, a
  classify miss, or an honest platform difference, and you have to know which.
  Record the outcome.

## 8. Docs

- `CLAUDE.md` — the import-capable set
- `docs/config-import.md` — the design record, if the platform taught something
  the model did not already say
- this file, if a trap was found that is not in it

---

## The planned order

Recorded 2026-08-11, post-v1.0 (ROADMAP item 24). Rationale in
`import-platforms-and-netlab-dependency.md`.

**1. FRR.** Admitted, so import → deploy → diff is a complete story. Its vtysh
config is IOS-flavoured `"block"` form, reusing machinery that already exists;
its interface names are Linux names, so the abbreviation table *shrinks*. The
open question to settle first: whether `show running-config` or the per-daemon
config files are the better source, and whether an FRR node's config should be
carried as one file or split per daemon.

**2. RouterOS 7.** Admitted, `"flat"` form. New wrinkle: `/export` uses trailing
`\` line continuations, which must be normalized before parsing, and its
section paths are deeper than VyOS's. Its quarantine list is the least
predictable of the three — RouterOS mixes system and service config more freely.

**3. Stop, and decide.** Beyond these two, every candidate (EOS, NX-OS, Junos)
is a platform Twinlab cannot deploy. Do not add one without an explicit decision
about what an un-deployable imported lab is *for*.

### Deliberately out of scope

- **Cross-platform import** ("parse Arista, emit FRR"). The carry is verbatim
  source config replayed onto the same NOS; crossing platforms means config
  translation, which would destroy the property that makes import trustworthy —
  that every source line is modeled, carried verbatim, or visibly quarantined.
- **Batfish as a universal parser.** It models rather than partitions, so the
  original text cannot be reconstructed and the completeness invariant is lost.
  Also a JVM service. Evaluated, not disqualified on licence (Apache-2.0), just
  wrong for this.
- **Structure-only import** (topology modeled, everything else quarantined,
  covering many platforms with one thin parser) is a *legitimate* alternative
  tier, and a product decision rather than an engineering one. It trades the
  fidelity promise for breadth. Not planned; recorded so it is not re-derived.
