# Definitions from config files (input methods, part two)

Design record of the 2026-08-04 discussion (ROADMAP item 16.4, part two — unparked the same
week part one shipped, taken up ahead of scenario definition). Decisions here are agreed with
the maintainer; contract delta 22 passed review (APPROVED 2026-08-04, after the
physical-vs-logical clarification below) and **SHIPPED the same day** across backend
(`services/configimport/`), client, blackbox (130/130 green live, incl. the deploy-marked
round trip: import two VyOS configs → compose → deploy with configure → the fidelity diff
reports zero missing lines) and frontend (the `/labs/import` wizard + the builder's "From
config file…"). Two facts were live-proven en route and folded back into the contract text:
the compose order is `put_custom_config` BEFORE `update_definition` (the definition PUT's dry
create validates `config:` references against the STORED fileset), and VyOS op-mode
collection over docker exec needs `/opt/vyatta/bin/vyatta-op-cmd-wrapper` (bare op-mode
commands return empty stdout).

## Goal

Turn **dumped running configs** from real devices into a deployable Twinlab lab: the user
supplies one config file per node (or a single file for one node), Twinlab produces a netlab
definition plus the config content netlab doesn't model, and the resulting lab **configures
correctly end to end** — a digital twin of the source network. Two granularities: a whole
network from N files, and a single node from one file (stamped into an existing definition,
shaped like the node-template flow).

## Established facts (verified 2026-08-04)

- **netlab has no import.** The 26.06 CLI is strictly definition → artifacts (`create`, `up`,
  `initial`, …); `collect` goes config-ward only for labs netlab itself deployed. Nothing
  consumes device configs to produce a topology. Import is ours to build; netlab's role is
  unchanged (the emitted definition lands through the existing `PUT`, whose dry `netlab
  create` remains the validator).
- **Parser landscape splits exactly along our supported set:**
  - *Cisco IOS*: **netutils** (Apache-2.0, verified against the 1.18.0 wheel) ships an
    `IOSConfigParser` producing a hierarchical parent/child config-line tree — structural,
    not semantic; we write small per-stanza extraction on top. **Batfish** (Apache-2.0) is
    the maximal option (full semantic model, even config-derived L3 adjacencies) but is a
    heavyweight Java service and supports no VyOS. **ciscoconfparse2 is GPLv3** — blocked in
    the backend; with netutils covering the structural role, a GPL sidecar is unjustified.
  - *VyOS*: covered by nothing — not Batfish (confirmed against their supported-platforms
    doc), not netutils, and VyOS's own Python libraries are GPL/LGPL. But VyOS is the easy
    half: `show configuration commands` output is flat `set …` lines (a trivial tree-build),
    and the brace format is equally mechanical. A small hand-rolled boundary parser is
    honest and unavoidable.
- **containerlab accepts embedded startup-config** (multiline string in the topology YAML),
  so a raw-clab path would survive our inline deploy. Verified — and still rejected, below.

## Rejected alternative: a second, raw-containerlab deployment model

Considered: skip netlab for imported labs — generate a clab topology directly and push the
config files onto the nodes verbatim (motivation: fear of losing information in
translation). Rejected 2026-08-04 because the simplification is smaller than it appears and
the cost lands elsewhere:

1. **Topology inference doesn't go away.** A clab topology needs explicit positional links;
   configs contain none. The subnet-join inference and the config-interface → veth-slot
   mapping are required in both models, and in raw clab the wiring must be exactly right.
2. **Verbatim push is only lossless when the source platform IS the lab platform.** A
   production dump says `GigabitEthernet0/0/1`; IOL's interfaces are `Ethernet0/0..3`,
   VyOS's are `ethN`. Interface renaming is physics of the hardware→lab move, not an
   artifact of the netlab path — verbatim push onto a different platform silently
   mis-configures.
3. **A second lab species forks the whole product.** Facts, test-suite rendering, the link
   table, drift, the builder, templates, the config-push path — all keyed on "the
   definition is netlab YAML". Every one would fork or degrade. Plus per-kind
   `startup-config` semantics vary across clab kinds.

The case where raw clab is strongest — same-platform re-import — is served equally well
inside the one-model design: the interface map degenerates to the identity and the carry is
character-for-character verbatim.

## Decisions (maintainer-approved 2026-08-04)

- **One deployment model: netlab.** Import is a **definition factory**: a pure
  transformation producing netlab YAML + per-node carried config, landing through the
  existing create/PUT composition. The lab never remembers its import origin (the
  delta-21 principle).
- **Nothing is dropped — every source line lands in exactly ONE of three buckets** (the
  builder's typed-vs-extras philosophy applied to import):
  1. **Modeled** — consumed into the skeleton; netlab regenerates it natively, so it must
     NOT also ride the carry (double-apply/conflict).
  2. **Carried** — verbatim in a per-node custom-config template, applied by `netlab
     initial` after module config (the existing mechanism). Untouched except interface
     renaming.
  3. **Quarantined** — kept but not applied by default: config that references the
     production environment rather than the network's own behavior and would break the lab
     (mgmt addressing — Twinlab's own; AAA/TACACS/RADIUS — locks out lab access;
     prod-pointing telemetry — NTP/SNMP/syslog/flow exporters; hardware/licensing lines).
     Stored visibly per node as unattached templates, re-attachable by the user, each line
     with its reason. The quarantine list is small, fixed, per-platform; routing policy,
     ACLs, QoS, VRFs are NEVER quarantined — they carry and apply.
  Completeness is a testable invariant: modeled ∪ carried ∪ quarantined = the source
  config; the raw dump also rides the import report verbatim.
- **Thin skeleton, fat carry.** The loss surface is proportional to how much is modeled
  semantically, so model only what topology-building structurally requires — nodes, links,
  **pinned addressing** (explicit per-endpoint IPs and loopbacks; address fidelity is the
  point of a twin) — and declare **no protocol modules by default**: OSPF/BGP/MPLS/ACLs/
  everything ride the carry verbatim. netlab then generates only interface/IP config (which
  matches the source, since pinned) and the carry does the rest. The loss surface collapses
  to two auditable transformations: the interface map and the quarantine list. Module
  modeling is a later, optional editability refinement (with ROADMAP item 19), never a
  correctness risk taken now.
- **Interface renaming via the expanded topology, two-phase.** Emit the skeleton → run the
  same dry `netlab create` the PUT runs → the expanded topology (the artifact the link
  table/facts already come from) pairs each source interface (identified by its
  subnet-inferred link endpoint) with the netlab-assigned lab ifname → rewrite the carried
  config with that map. The map goes in the report so any line is traceable. Same-platform
  imports get the identity map.
- **Prove fidelity, don't trust it.** After deploy + configure, collect each node's running
  config (over the existing exec transport) and diff it against the supplied source, modulo
  the interface map and quarantine — a three-way classified report (missing-from-lab /
  extra-in-lab / matched), informational, never a gate. The check is stateless: sources are
  supplied in the request, because the lab does not remember its origin.
- **Scope: the supported device set only** (VyOS + Cisco IOS/IOL) — the same policy
  boundary as the catalog; the NOS platform sweep (item 17) widens both together.
- **Batfish set aside, not rejected**: if its topology inference ever earns its infra
  weight, it slots behind the same normalized facts model.

## Architecture (the pipeline)

```
per-file parse (VyOS set/brace: own boundary parser · IOS: netutils structural tree)
  → normalized facts model (hostname, interfaces + addresses, stanza tree w/ bucket tags)
  → link inference (join interfaces by subnet: 2 → p2p, 3+ → LAN, unmatched → stub)
  → skeleton emission (nodes + links, pinned IPs/loopbacks, sanitized names + name map)
  → dry netlab create → source-if → lab-if interface map
  → carry rewrite (interface renaming) + quarantine split
  → result: definition + per-node carried templates + quarantined templates + report
```

All backend, no new service. `try`/`except` only at the parse boundaries; errors as values;
the classifier is one function shared by carry-split and the completeness invariant.

### Physical vs logical topology (clarified at review, 2026-08-04)

Import recovers the **logical (L3) topology, deliberately** — configs cannot contain the
cabling (that lives in CDP/LLDP state, not running config; even Batfish requires a
user-supplied `layer1_topology.json` for physical wiring and derives its config-based edges
from the same subnet join). A netlab lab is itself a logical topology, so the match is exact:
routed p2p links are recovered faithfully (veth pairs); a multi-access subnet becomes ONE LAN
link — collapsing any physical switch fabric between the routers into one bridge, which is
L3-equivalent (same adjacencies, same forwarding: the layer Twinlab tests); interfaces whose
peer is outside the import set become stubs (the twin's boundary, config still applied).
Honest limits, all named warnings, never silent: unnumbered links and mask mismatches don't
join (stub + warning), and **LAGs** are the worst case — the port-channel's subnet joins but
its unaddressed member interfaces don't exist in the lab, so carried member references warn
loudly (modeling `lag` is a module promotion for ROADMAP item 19, not a v1 correctness risk).
The wizard's review step is the human backstop: the factory output is an ordinary builder
doc, rendered on the canvas before any lab exists — inference proposes, the user disposes.
**Recorded future extension** (not v1): optionally accept CDP/LLDP neighbor dumps or an
explicit wiring list as auxiliary input to pin adjacencies addressing can't distinguish
(parallel links, L2 paths) — the Batfish-layer1 precedent. **Sequenced (maintainer,
2026-08-04): this analysis happens immediately after the v1 implementation ships**, not at
an unspecified later date.

## Implementation plan

Order and gates per house convention (small commits; backend: ruff + basedpyright strict +
pytest; frontend: typecheck + build; full test output to files; contract items pause for
review). **New dependency `netutils` (Apache-2.0) needs explicit approval before `uv add`.**

1. **Contract delta 22 sketch** in `docs/twinlab_client_shape.py` → ⛔ **review pause**.
   Proposed shape (final form at review): `POST /import/network` `{sources: [{device,
   content, name?}]}` → `{definition, node_configs, quarantined, interface_maps, warnings}`
   (synchronous — cost ≈ a PUT's dry create; `lab:create`); `POST /import/node` `{device,
   content}` → fragment + carry + report; `POST /labs/{name}/config-diff` `{sources}` → the
   fidelity report (runs execs; permission and deferability are review items).
2. **Backend: VyOS parser + facts model** — set-format and brace-format both; pure code.
3. **Backend: IOS parser** over netutils (post-approval): structural tree → same facts model.
4. **Backend: link inference + skeleton emission** — subnet join, pinned addressing,
   hostname sanitization with the name map in the report.
5. **Backend: two-phase interface map + carry rewrite + quarantine classifier** — rewrite
   exact names and canonical abbreviations; interface-like tokens that match nothing are a
   named warning, never silent.
6. **Backend: the import endpoints**; **7. config-diff**; **8. client** (mirrored methods);
   **9. blackbox** — cheap factory tests (fixtures + the completeness invariant) plus the
   flagship deploy-marked round-trip: deploy an example lab, collect its running configs
   over exec, feed them to the importer, deploy the import, and expect a near-clean
   fidelity diff (self-hosted ground truth; fixtures generated from our own labs, so
   license-clean).
10. **Frontend** — an import wizard (upload/paste N configs with per-file device select →
    review step: definition editor + per-node carry/quarantine viewer + report → name +
    compose create/PUT/templates) reached from the labs page beside "Start from"; the
    builder's Add menu gains "From config file" for the node granularity.
11. **Docs + memory** — CLAUDE.md, ROADMAP outcome, this file's status, blackbox README.

## Open items pinned for the contract-sketch review

- Quarantine class list per platform (proposed above) — confirm/adjust.
- `config-diff`: ship in v1 or defer to a fast-follow (the import path stands without it).
- Import endpoint permission (`lab:create` proposed) and the sync-vs-job call.
- Abbreviated interface references in carried IOS config (`Gi0/0/1` in `ip route` etc.):
  rewrite canonical abbreviations + warn on unmatched, or warn-only.
- Wizard entry points (labs page + builder Add menu proposed).
