# Builder coverage gaps — full inventory (2026-08-04)

Analysis input to ROADMAP item 17, strand 17.3. Decisions are the maintainer's; the picture is
presented, nothing is chosen here.

Netlab reference: **netlab 26.07**, installed at
`backend/.venv/lib/python3.14/site-packages/netsim/` (paths below abbreviated `netsim/`).
Builder reference: `frontend/src/lib/build-doc.ts` (the parser/emitter),
`frontend/src/lib/device-catalog.ts` (BUILDER_MODULES + catalog shape).

Tiers: **A** = structurally rejected by `parseBuildDoc` (whole doc falls back to Text mode);
**B** = parses into `extras` (lossless round-trip, raw-YAML editing in "Advanced properties");
**C** = typed (first-class visual editing).

---

## 1. The current gates and typed surface (exact)

### 1.1 Every parse gate (Tier A trigger), with its message

All in `frontend/src/lib/build-doc.ts`:

| # | Gate | Message | Line |
|---|------|---------|------|
| G1 | Invalid YAML | `not valid YAML: <err>` | 644–647 |
| G2 | Doc not a mapping | `the definition is not a YAML mapping` | 649 |
| G3 | Node name outside `[A-Za-z_][A-Za-z0-9_]*` or >24 chars (covers **hyphenated names**) | `node name "X" is outside the builder's rules (letters, digits, underscores; max 24)` | 357–360 |
| G4 | Node value not empty/mapping | `node "X" must be empty or a mapping of attributes` | 363–365 |
| G5 | `nodes:` list entry not a plain string (netlab also accepts `{name: …}` dicts) | `node list entry <desc> is not a plain name` | 742–744 |
| G6 | `nodes:` neither mapping nor list | `"nodes" must be a mapping or a list of names` | 751 |
| G7 | **Unknown device** (node or `defaults.device`) — the POLICY gate | `… device "X" is not in the builder's catalog` | 333–348, 664–687 |
| G8 | String link not an `a-b` pair | `link N ("…") is not an "a-b" endpoint pair` | 509–514 |
| G9 | List-form link with non-string members (netlab accepts `{node:, …}` dicts mixed in) | `link N must be a list of node names` | 516–522 |
| G10 | Link entry not string/list/mapping | `link N (<desc>) is not a link form the builder knows` | 524–527 |
| G11 | `interfaces` not a list / record missing `node` | `"interfaces" must be a list of {node, …} records` / `every interfaces record needs a "node" name` | 536–546 |
| G12 | **Interfaces form mixed with node keys** | `link N mixes the interfaces form with node keys` | 548–556 |
| G13 | Dict-form endpoint value a scalar | `endpoint "X" must be empty or a mapping of attributes` | 562–567 |
| G14 | **Link groups / attribute-only entries** (no declared node among the keys) | `link N has no declared node as an endpoint (link groups and attribute-only entries are text-editor territory)` | 575–580 |
| G15 | **Dict-of-lists `links:`** | `"links" must be a list (the dict-of-lists form is text-editor territory)` | 590–593 |
| G16 | **Undeclared link endpoint** (incl. component-expanded names like `<node>_<member>`) | `link N references undeclared node "X"` | 602–605 |
| G17 | **Self-links** (a node twice on one link) | `link N lists a node more than once (self-links are text-editor territory)` | 607–609 |

Emit-time SAVE BLOCKERS (not parse gates, but part of the boundary): empty lab, device-less
node with no `defaults.device` (840–853 — notable interaction with `components`, §3.1.8),
undeclared vrf membership, 2-member LAN, link-extras key naming a declared node, undeclared
group member unless the group sets `_auto_create` (878–887), typed/extras same-key collision
(821–915).

### 1.2 The typed surface (Tier C today)

| Level | Typed keys | Line |
|---|---|---|
| Lab | `name`, `provider`, `defaults.device` (dotted or split out of `defaults:`), `module` (exact BUILDER_MODULES lists only), `bgp.as` (number), `mpls.ldp` (bool), `vrfs` (bare declarations only), `groups`, `addressing` (mgmt shape only, backend-managed), `nodes`, `links` | 654–736 |
| Node | `device`, `image`, `module`, `bgp.as` / `bgp: {as}`, `mpls.vpn` / `mpls: {vpn}`, `vrfs` (empty or `{loopback: bool}` entries) | 350–418 |
| Group | `members` (string list), `config` (string list) | 465–493 |
| Link | kind by endpoint count (stub/p2p/LAN), `name`; string, list, dict AND interfaces forms all parse (interfaces re-emitted as dict) | 495–627 |
| Endpoint | node identity only — every attribute is endpoint `extras` | 58–65 |

**All-or-nothing shape rules that silently demote to B** (the key nuance for "is X typed?"):
- `module:` containing ANY module outside `{ospf, bgp, mpls, vrf}` → the WHOLE list rides
  extras and the Global/Node modules control disables (`modulesShape`, 151–161).
- `bgp:` as a mapping with anything beyond `as` (e.g. `router_id`) → whole `bgp` key to
  extras (`bgpShape`, 163–167). So **`bgp.as` is typed; `bgp: {as, router_id}` is extras
  including the `as`**.
- `mpls:` carrying both `ldp` and `vpn` (or any other key) → whole key to extras (169–173).
- `vrfs:` where any vrf carries attributes (`rd`, `rt`, …) → whole `vrfs` key to extras;
  node membership still validates against those names via `declaredVrfs` (175–187, 314–320).
- `groups:` whose values are not all mappings (e.g. a groups-level `_auto_create: true`) →
  the ENTIRE `groups` key lands in doc extras and the Groups UI shows nothing (465–468).
- `addressing:` beyond the exact backend-injected mgmt shape → extras (211–223).

---

## 2. Netlab 26.07 syntax inventory, tier-classified

Sources: core schema `netsim/defaults/attributes.yml` (global/node/link/interface/loopback/
pool/prefix/node_group sections); per-module `netsim/modules/*.yml`; plugins `netsim/extra/`;
link forms `netsim/augment/links.py`; nodes forms `netsim/augment/nodes.py:37`; components
`netsim/augment/components.py`; id rule `netsim/data/types.py:487–501`
(`[a-zA-Z_][a-zA-Z0-9_-]{0,15}` — **netlab node names allow hyphens**, max 16 chars).

### 2.1 Document / structural forms

| Feature | netlab ref | Tier | Evidence |
|---|---|---|---|
| `nodes:` as mapping | nodes.py:37–66 | **C** | build-doc.ts:746–749 |
| `nodes:` as list of strings | nodes.py:47 | **C** (normalized to mapping on emit) | build-doc.ts:742–743 |
| `nodes:` as list of `{name: …}` dicts | nodes.py:43–49 | **A** (G5) | build-doc.ts:744 |
| Hyphenated node names | types.py:492 id regex | **A** (G3) | build-doc.ts:357 |
| `links:` list of string `a-b` | links.py:175 | **C** | build-doc.ts:508–514 |
| `links:` list-form (list of node names) | links.py:170 | **C** | build-doc.ts:516–522 |
| List-form with `{node:, …}` dict members | links.py adjust_interface_list | **A** (G9) | build-doc.ts:517–521 |
| Dict-form link | links.py:155–168 | **C** | build-doc.ts:557–574 |
| Interfaces-form link | links.py:149–153 | **C** (re-emitted as dict form) | build-doc.ts:531–556 |
| **Dict-of-lists `links:`** (named sub-lists) | links.py:206–211 | **A** (G15) | build-doc.ts:590–593 |
| **Link groups** (`group:` + `members:`) | links.py:1312–1363 (expand_groups) | **A** (G14) | build-doc.ts:575–580 |
| Attribute-only link entry (no endpoints) | invalid in netlab too (0 interfaces) | **A** (G14) — aligned | build-doc.ts:575–580 |
| Scalar endpoint value | invalid in netlab (`must_be_dict`, links.py:161) | **A** (G13) — aligned | build-doc.ts:562–567 |
| Interfaces form + node-key siblings | netlab treats siblings as link attrs (no discrimination), then fails validation | **A** (G12) — roughly aligned | build-doc.ts:548–556 |
| **Self-links** (same node twice) | valid netlab (two interfaces on one node; spellable only in list/interfaces form) | **A** (G17) | build-doc.ts:607–609 |
| **`components:` + node `include:`** | components.py (expands to groups/nodes/links; expanded names `<includer>_<member>`) | **B** for the keys themselves; **A** when links reference expanded names (G16 — `is_nodename_valid` accepts include prefixes, links.py:87–95; the builder doesn't) | build-doc.ts:602–605, 734 |

### 2.2 Top-level (global) keys

| Key | netlab ref (attributes.yml `global`) | Tier | Notes |
|---|---|---|---|
| `name` | global.name | **C** (backend-injected, preserved) | build-doc.ts:656–658 |
| `provider` | global.provider | **C** (string field) | 660–662 |
| `defaults.device` | defaults ns | **C** (policy-gated G7) | 664–687 |
| `defaults` (everything else: device params, images, `defaults.*` tuning) | global.defaults | **B** (split: rest → extras) | 668–687 |
| `module` | global.module | **C** if ⊆ BUILDER_MODULES, else **B** whole-list | 689–693 |
| `addressing` (pool definitions) | global.addressing, pool section | **B** (mgmt shape only is typed) | 724–728 |
| `prefix` (named prefixes) | global.prefix, _prefix section | **B** | 733–734 |
| `plugin` | global.plugin | **B** | 733–734 |
| `tools` (graphite/suzieq/…) | global.tools | **B** (and silently dropped by Twinlab deploy — see netlab-up-gaps.md gap 2) | 733–734 |
| `validate` (netlab validation tests) | global.validate, _v_entry | **B** (Twinlab has its own suites) | 733–734 |
| `version`, `message` | global.version, internal.message | **B** | 733–734 |
| `groups` | global.groups, node_group section | **C** (members/config) / **B** per-key / whole-key **B** if any value non-mapping | 721–722, 465–493 |
| `vlans` (VLAN definitions: id, vni, mode, prefix, …) | vlan module `_top` | **B** | 733–734 |
| `vrfs` bare | vrf module `_top` | **C** | 715–719 |
| `vrfs` with attributes (rd/rt/import/export/loopback) | vrf module | **B** whole-key | 178–187 |
| `bgp.as` | bgp module global | **C** | 695–703 |
| Any other module global attr (`ospf.area`, `bgp.sessions`, `isis.type`, `gateway.protocol`, …) | modules/*.yml global sections | **B** | 733–734 |
| `mpls.ldp` | mpls module | **C**; `mpls: {ldp, vpn}` combined → **B** | 705–713 |

### 2.3 Node attributes

Core (attributes.yml `node`): `box`, `config`, `cpu`, `group`, `id`, `interfaces`,
`loopback`, `memory`, `mgmt`, `module`, `mtu`, `name`, `provider`, `role`, `router_id`,
`skip_config`, `unmanaged` + `include` (components) + per-module node attrs.

| Attribute | Tier | Notes |
|---|---|---|
| `device`, `image`, `module` (⊆ builder set), `bgp.as`, `mpls.vpn`, `vrfs` (bare/loopback) | **C** | build-doc.ts:369–411 |
| Everything else above, incl. `loopback`, `mgmt`, `mtu`, `cpu`/`memory`/`box`, `id`, `role`, `config` (node-level custom config — typed only at GROUP level), `group`, `include`, `unmanaged` | **B** | default arm 412–413 |
| Module node attrs of TYPED modules beyond the typed key: `bgp.router_id`, `bgp.rr`, `bgp.local_as`, `ospf.area`/`ospf.router_id`, `mpls.bgp`/`6pe`, `vrf.as`… | **B** | The "is `bgp.as` typed but `bgp.router_id` extras?" answer: yes — and a combined `bgp: {as, router_id}` mapping drags `as` into extras too (163–167) |
| Module node attrs of untyped modules (isis.net, lag.mlag, stp.priority, …) | **B** | |

### 2.4 Link attributes (link level)

Core (attributes.yml `link`): `bandwidth`, `bridge`, `disable`, `mtu`, `name`, `pool`,
`prefix`, `ra`, `role`, `shutdown`, `tc` (netlab impairment — netlab-up-gaps.md gap 1's
silently-ignored key), `type`, `unnumbered`, `vlan_name` + module link attrs (`ospf.cost/area/
passive/network_type`, `vlan.access/trunk/native/mode`, `lag.*` incl. `lag.members`,
`gateway.*`, `stp.*`, `isis.*`, `mpls.ldp`, `bfd.*`, `dhcp.*`, `vxlan.vtep`, `vrf`).

Only `name` is **C** (553–554, 568); everything else is **B** (link extras, 570–571, 581),
with the constraint that a link-extras key can never equal a declared node name (303–312,
emit blocker 867–876).

### 2.5 Endpoint (interface) attributes

Core (attributes.yml `interface`): `ifindex`, `ifname`, `ipv4`, `ipv6` + module interface
attrs (`ospf.priority`, `bgp.local_as`, `stp.port_priority`, `lag.lacp_system_id`,
`dhcp.client/server`, `vrf`, `vlan.*`, …). All **B** — endpoint extras (545–546, 563).
Nothing endpoint-level is typed.

### 2.6 Group attributes

| Attribute | Tier |
|---|---|
| `members`, `config` | **C** (475–487) |
| `device`, `module`, `node_data`, `vars`, `_auto_create`, broadcast module attrs (`bgp.as` on an as-group, …) | **B** (group extras; `_auto_create` emit-waived 878–882) |
| BGP auto-groups (`as65000` naming) | **B** (just a name) |
| Hierarchical groups (a group as a member) | **B** at parse, but the undeclared-member emit blocker fires unless `_auto_create` (884–886) — effectively **A-at-save**. netlab allows it. |

### 2.7 Modules (18 in `netsim/modules/`)

| Module | Tier | Notes |
|---|---|---|
| `ospf` | **C** presence; all attrs (area, cost, passive, bfd, timers, reference_bandwidth, vrf-level) **B** | |
| `bgp` | **C** presence + `bgp.as` (lab/node); the other ~25 attrs (rr, sessions, community, local_as, confederation, policy…) **B** | |
| `mpls` | **C** presence + `mpls.ldp` (lab) + `mpls.vpn` (node); `6pe`, `bgp`, link `ldp` **B** | |
| `vrf` | **C** presence + bare declarations + node membership `{loopback}`; vrf attrs (rd/rt), link/interface `vrf:` placement **B** | |
| `bfd`, `dhcp`, `eigrp`, `evpn`, `gateway`, `isis`, `lag`, `ripv2`, `routing`, `sr`, `srv6`, `stp`, `vlan`, `vxlan` | **B** — BUT with the demotion trap: naming any of them in `module:` demotes the whole module list to extras and disables the modules control (151–161). `lag` is the named promotion candidate (config-import). |

### 2.8 Plugins (`netsim/extra/`, ~24)

`bgp.domain/originate/policy/session`, `bonding`, `check.config`, `ebgp.multihop/utils`,
`evpn.multihoming`, `fabric`, `files`, `firewall.zonebased`, `kind`, `mlag.vtep`,
`multilab`, `multiserver`, `node.clone`, `none`, `ospf.areas`, `proxy_arp`, `test.*`,
`tunnel` (gre/wireguard), `vrrp.version` — all **B**: the `plugin:` list and every
plugin-defined attribute ride extras.

---

## 3. Promotion assessments

> **Status 2026-08-04: the Tier A batch below is SHIPPED** — items 3–9 (hyphenated names +
> the 16-char cap, nodes-as-dict-list, list-form dict members, dict-of-lists links, link
> groups, components' minimum step, self-links) and the hierarchical-group-member emit
> blocker in §2.6. Sections 1 and 2 describe the state BEFORE that batch and are kept as the
> inventory that produced it; §4's "9 genuinely promotable" count is now zero. What remains
> open is Tier B (§3.2), deferred to its own review before v1.0, and the unknown-device
> policy gate, which moves with 17.1.
>
> Verified by a 36-check round-trip harness (esbuild bundle under node), by all five stored
> definitions on the running stack, and against netlab 26.07 itself: every emitted form
> creates cleanly, and the builder's link-group expansion produces a byte-identical expanded
> topology to netlab's own. One live finding rode along — a self-link's two ends draw the
> SAME pool address (netlab derives it from the node id), so `netlab create` refuses it
> unless the link says `prefix: false` or each end carries an explicit `ipv4`; the link
> inspector says so rather than blocking the save.

### 3.1 Tier A — inherent vs promotable

1. **Invalid YAML / non-mapping doc (G1, G2): inherent.**
2. **Scalar endpoints, attribute-only entries, malformed interfaces records, unknown
   link-entry types (G13, non-group G14, G11, G10): aligned with netlab** — netlab errors
   on these too (links.py:161, empty interfaces, type errors). Not coverage gaps.
3. **Hyphenated node names (G3): promotable to C, small-medium.** netlab allows `-`
   (types.py:492). Only hazard is the terse `a-b` string form (ambiguous in netlab itself).
   Fix: widen `EXISTING_NAME_RE`, and have `linkYaml` refuse the string form when any
   endpoint name contains a hyphen (emit list form). `NODE_NAME_RE` for new names can stay
   strict. Nit: netlab caps ids at 16 chars, the builder allows 24 — the dry create catches it.
4. **Nodes as list-of-dicts (G5): promotable to C, small.** Normalize on parse; emit is
   already canonical mapping (list→mapping rewrite on first save, semantically identical).
5. **List-form links with dict members (G9): promotable to C, small.** Same shape as
   interfaces-form records; parser-only change.
6. **Dict-of-lists `links:` (G15): promotable, small-medium.** netlab just flattens named
   sub-lists (links.py:206–211). Choice: flatten on parse (simple, grouping lost on save)
   vs a typed per-link `listName` for lossless re-emit (touches BuildLink/canonical/emit).
7. **Link groups (G14): promotable, medium.** netlab copies group data down into member
   links (links.py:1312–1363). Expand-on-parse is the cheap honest option (lossy on save);
   a typed link-group entity implies unclear canvas UI.
8. **Components / include: promotable only as a package, large.** The keys already ride
   extras (B), so a components doc parses — until a link references an expanded name
   (`<includer>_<member>`), which G16 rejects (netlab whitelists include prefixes,
   links.py:87–95). Also: include nodes have no `device`, so the emit blocker (846–848)
   blocks Visual saves unless `defaults.device` is set. Minimum honest step: teach G16 the
   include-prefix rule + waive the device blocker for include nodes (small); real
   see-through support (expanding on the canvas) is large.
9. **Self-links (G17): promotable, medium.** Valid netlab; the dict form can't spell a
   duplicate key, so emit must switch to interfaces form for them, endpoint identity must
   go beyond node name, and the canvas needs a self-loop edge. Niche value.
10. **Interfaces + node keys mixed (G12): near-inherent, recommend keep** — netlab doesn't
    discriminate node-key siblings there either.
11. **Unknown device (G7): policy, zero parser work** — widens with the NOS sweep's catalog
    (17.1); `parseBuildDoc` already takes the device list as a parameter (638). This is the
    shared 17.1/17.3 boundary.

### 3.2 Notable Tier B promotions to C

| Feature | Size | Sketch / UI | Catalog constraint |
|---|---|---|---|
| **`lag` module** (named candidate) | medium | Add to BUILDER_MODULES (also fixes the whole-list demotion) + link `lag.*` fields; badge LAG bundles on canvas. Config import already produces lag-adjacent labs. | `CatalogDevice.modules` = server matrix ∩ BUILDER_MODULES — server `GET /catalog` and `use-device-catalog.ts` widen together; support per sweep |
| Module **presence-only** promotion (isis, stp, bfd, gateway, dhcp, eigrp, ripv2, sr, srv6, evpn, vxlan, vlan, routing) | small each | Checkbox in the modules control, greyed by the device×module matrix. Big win: ends the trap where ONE exotic module makes even `ospf` raw YAML. | same |
| `bgp` overflow (`router_id`, `rr`, …) | small–medium | Per-subkey split (precedent: the `defaults:` split at 668–687) instead of whole-key `bgpShape`. | none |
| `vrfs` with attributes (rd/rt) | small–medium | Typed vrf record + rd/rt fields in the VRF editor. | none |
| Link `bandwidth`/`mtu`/`prefix` | small | Inspector fields; already round-trip as extras. | none |
| Link `tc:` | small | Sequence AFTER the gap-1 deploy-semantics decision (netlab-up-gaps.md) — typing a silently-dropped key is UI over a no-op. | none |
| Endpoint `ifname`/`ipv4`/`ipv6` | small–medium | Per-endpoint inspector fields; common in imported labs. | none |
| `vlans:` + `vlan` module | large | VLAN palette, per-link access/trunk UI, canvas semantics — netlab's most complex propagation module. | sweep |
| Node `loopback`/`mgmt`/`mtu`/`cpu`/`memory`/`role`/node-level `config` | small each | Plain fields; node `config` mirrors the group template picker. | none |
| `plugin:` list | small (presence) / large (semantics) | String-list control is cheap; plugin-injected attributes open-ended. | none |
| `addressing`/`prefix` pools | medium | Pool editor; backend re-pins `addressing.mgmt` on PUT — only non-mgmt pools are user territory. | none |
| `tools:`/`validate:` | — | Gap-2 decision leans explicit out-of-scope; Twinlab has its own validation. Recommend stay B. | — |
| Groups parse nuance | small | Fix the whole-`groups`-to-extras trap on non-mapping values (465–468); typed `_auto_create` toggle; relax hierarchical-member emit blocker. | none |

## 4. "If we chose to support everything" totals

- **17 Tier A gates**: 2 inherent (invalid YAML, non-mapping), 4 aligned-with-netlab
  (nothing to promote), 1 near-inherent (interfaces+node keys), 1 policy (unknown device —
  moves with the sweep, no parser work), leaving **9 genuinely promotable**: hyphenated
  names (S-M), nodes-as-dict-list (S), list-form dict members (S), dict-of-lists links
  (S-M), link groups (M), self-links (M), component-expanded endpoints (S name-rule / L
  full), hierarchical group members (S, emit-side), + the 16-char id nit.
- **Modules: 4 of 18 typed** (presence + 4 attributes total); 14 promotions possible, cheap
  at presence level, arbitrarily deep per-attribute; all gated by the delta-18 device×module
  matrix the sweep settles.
- **Plugins: 0 of ~24**; presence-typing `plugin:` is one small change.
- **Attribute surfaces** (link ~14 core + ~30 module, endpoint 4 + ~15, node ~17 core): all
  B today, individually small, none blocking since extras editing covers them.
- **Text-only forever**: only invalid YAML, non-mapping docs, and netlab-invalid forms —
  no other inherent wall exists.

## 5. Examples cross-check

All three definitions in `examples/` are **fully buildable today**: `mpls-l3vpn.iol.yml`
(every key typed, incl. the groups block), `mpls-l3vpn.yml` (diff is only
`defaults.device: vyos` and no groups), and `campus-lan.yml` (dict/list/stub link forms;
its `bandwidth`/`mtu` ride link extras — Tier B, not gated). The repo's examples exercise
none of the Tier A forms — the gated territory is exactly the syntax Twinlab hasn't needed
yet, consistent with 17.3's promote-deliberately framing.

*(Written before `examples/mixed-nos.yml` landed 2026-08-05. It too is fully buildable:
per-node `device` + `module`, one `image:` override, p2p/LAN/stub links, no Tier B key at
all.)*

---

# 6. Tier B review · 2026-08-05

The review ROADMAP 17.3 deferred. Sections 1–5 are the inventory; this is the decision
pass over §3.2. **Nothing here is decided — every RECOMMEND waits on the maintainer.**

## 6.1 The bar

Tier B costs nothing structural. Every key in it round-trips losslessly, edits as YAML in
"Advanced properties", and deploys exactly as authored — the Tier A batch removed the last
forms that could push a document out of Visual mode entirely. So "promote everything" is
not the goal and neither is a size-ordered shopping list; **the v1.0 question is narrower:
where does leaving a key in Tier B make something we already ship look broken?** Three
findings answer that, and they are what the recommended slate is built from. Everything
else waits, on purpose — a typed control is a promise about a shape, and each one we add
is a shape we then owe compatibility to.

## 6.2 The three findings

**F1 — one exotic module empties the protocol UI.** `modulesShape` is all-or-nothing
against `BUILDER_MODULES = {ospf, bgp, mpls, vrf}`, so `module: [ospf, isis]` puts the
WHOLE list in lab extras. `doc.modules` is then `[]` — and the BGP-AS, LDP-transport and
VRF controls are all rendered behind `doc.modules.includes(...)` gates
(`inspector.tsx:640, 660, 683`). The cascade is the finding: adding one module the builder
doesn't know **removes the visual editing of the four it does know**, on a lab that is
otherwise entirely typed. The inspector is honest about it ("managed in Advanced
properties") but the honesty doesn't help — the user came to edit OSPF.

The fix is a vocabulary widening, not new controls, and it is nearly free: `GET /catalog`
already serves netlab's FULL per-device module matrix and `use-device-catalog.ts` throws
away everything outside `BUILDER_MODULES` (`:30`). **Zero backend work.** Scope, counted
against the six admitted devices: netlab 26.07 has 18 user modules
(`netsim/modules/*.yml` minus `initial`); the union of what our six support is **17 —
every one except `eigrp`**, which no admitted device runs.

**F2 — config import produces labs that are 100 % Tier B.** `services/configimport/emit.py`
emits exactly four things beyond node names and link membership, and all four are extras:
node `loopback: {ipv4}`, node `config: [imported/<n>.j2]`, link `prefix:` (a CIDR or
`false`), endpoint `{ipv4: <cidr>|false}`. Address fidelity is the entire point of an
imported twin, so **every meaningful value in a lab produced by yesterday's feature is raw
YAML in the builder** — and the import wizard hands the user straight to that lab. This is
the finding that turns "nice to have" into "we ship a seam".

**F3 — one of our own examples is Tier B.** `campus-lan.yml` sets link `bandwidth`/`mtu`
(and its header calls them out as a thing the example demonstrates). Two typed number
fields close it.

## 6.3 Recommended slate

Frontend-only, all of it — no contract change, no backend change, no migration.

### Class 1 · Widen the module vocabulary *(F1)* — RECOMMEND

Take `BUILDER_MODULES` from netlab's own module list rather than the four the builder has
controls for, and separate **vocabulary** (what parses typed) from **offer** (what gets a
checkbox):

- vocabulary = netlab's 18, so no module list is ever demoted;
- offer = the modules at least one cataloged device supports (17 today — `eigrp` gets no
  checkbox), plus any module already present in the document, so a key is never
  un-removable;
- per-device greying already exists (`deviceSupports`, `inspector.tsx:1041`) and starts
  doing real work the moment the intersection widens.

Presence-only is the honest promise: the module goes in the list, its attributes
(`isis.net`, `stp.priority`, …) stay extras. For `vlan`/`vxlan`/`evpn` a bare presence is
close to inert without their `vlans:` definitions — that is fine, the dry `netlab create`
stays the judge; we are removing a trap, not claiming support.

The one real cost: `FALLBACK_DEVICE_CATALOG` currently says "all four" for four devices
because the intersection made that true. It needs the real per-device lists mirrored from
`SUPPORTED_DEVICES` — a new drift surface between frontend and backend, though the
admission procedure already requires both to move together (step 1).

### Class 2 · Per-subkey splits, killing the sibling-drags-the-key rule — RECOMMEND

The same shape as F1's cascade, one level down, and the same reasoning **delta 26 just
settled for the fact namespace**: partition per object, not per top-level key, so an
unpinned sibling never hides a pinned member.

| Today | After |
|---|---|
| `bgp: {as, router_id}` → whole key extras, **`as` included** | `as` typed; `{router_id}` rides `bgp` extras |
| `mpls: {ldp, vpn}` → whole key extras | each typed; the rest rides `mpls` extras |
| `vrfs:` where ANY vrf has `rd`/`rt` → whole key extras | the vrf NAME list typed; per-vrf attributes ride extras keyed by name |
| `groups:` with one non-mapping value → **entire groups UI disappears** | that entry rides extras; the rest edit normally |

Emission merges the halves back into one mapping (`bgp: {as: 65000, router_id: …}`) rather
than leaning on netlab's dotted-key merge the way the `defaults.device` split does — same
result, one less netlab behaviour to depend on. The advanced editors gain sub-key errors
("the `as` subkey is owned by the BGP AS control"), keeping the one-classifier invariant.

Note this deliberately does NOT type `rd`/`rt`/`import`/`export` (§3.2 floats it): the
split alone removes the trap, and their shapes are list-valued and route-target-shaped —
a control worth building only on demand.

### Class 3 · The import surface *(F2)* — RECOMMEND

Typed fields for exactly the four keys the factory emits:

- **link `prefix`** — string CIDR **or `false`** (delta 23's unnumbered/L2 wire). The dict
  form (`{ipv4, ipv6, allocation}`) stays extras.
- **endpoint `ipv4` / `ipv6`** — string **or `false`** (delta 23 spells `ipv4: false` on
  the addressed-mixed wire, and netlab invents an address without it), plus **`ifname`**,
  which imported labs carry for interface-name fidelity. This is the first typed field at
  the endpoint level; the inspector already has a per-endpoint section to put it in.
- **node `loopback`** — the `{ipv4}`/`{ipv6}` subset only; `{pool: …}` and the bool form
  stay extras.
- **node `config`** — the string list, reusing the group section's template picker.

Cross-check when this lands: `SelfLinkAddressingHint` (`inspector.tsx:1356`) reads
`link.extras['prefix']` and the endpoints' `extras['ipv4']` directly — it must read the
typed fields or it will stop firing exactly when the user starts using the new controls.

### Class 4 · Link `bandwidth` / `mtu` *(F3)* — RECOMMEND

Two number fields beside `prefix`, netlab's own bounds on `mtu` (64–9216). Small, and it
retires the last Tier B key in `examples/`.

### Class 5 · Three node attributes, added by the 2026-08-05 re-analysis — RECOMMEND

The first pass excluded the node core attributes on "no evidence anyone edits them" —
which is a sample of one maintainer, not evidence. Re-derived from netlab 26.07's source
(§6.4.1), three of them turn out to belong in the slate for the SAME reason as F1: not
because they are cheap, but because the builder currently shows something untrue.

- **`box` — a typed control that lies.** `box` and `image` are ONE setting, and `box`
  WINS: `augment/nodes.py:335–341` returns early on `n.box` before ever looking at
  `n.image` (which it otherwise moves into `box` and deletes). The builder types `image`
  and leaves `box` in extras — so a node carrying `box:` shows an EMPTY, editable Image
  field while the advanced properties silently decide the image, and editing the field
  changes nothing. Fix: one control, both spellings, remembering which was authored (the
  `listName` precedent) and preferring `box` when a document sets both, exactly as netlab
  does.
- **`group` — the second spelling of a relationship the builder already models.**
  `augment/groups.py:405–423` appends a node's `group:` entries straight into
  `groups[<name>].members`; the two spellings are indistinguishable after expansion. Today
  the node-side one rides node extras, so the Groups UI UNDERSTATES membership — a group
  whose members all declare themselves node-side renders empty. Fix: parse it into the
  member list and emit the canonical `members:`, with a notice — the link-group
  expand-on-parse pattern from Tier A, and it must be proven the same way (byte-identical
  expanded topology).
- **`role` — an enum with consequences.** `nodes.py:224` gives a loopback interface only to
  `role: router` (the bird asymmetry documented in `mixed-nos.yml`), and `nodes.py:481–489`
  validates the value against a PER-DEVICE allowed set. A select beats a free-text YAML
  key: four values, real behaviour behind them, per-device validation available. The
  weakest of the three — it fixes no lie — but it clears the §6.4.2 bar on its own.

## 6.4 Deliberately NOT in the slate

**Re-derived 2026-08-05.** The first pass leaned on "no demand" for several of these,
reading demand off `examples/`, the import output and the sweep labs — i.e. off one
maintainer's use of the tool. That is not evidence about users, so each exclusion below now
rests on netlab's own behaviour or on an intrinsic property of the key. Where the honest
reason turned out to be different, the entry moved (three of them into Class 5).

### 6.4.1 Inert under the provider we deploy through

- **Node `cpu` and `memory`** — libvirt-only in netlab 26.07: the sole consumer is
  `templates/provider/libvirt/define-domain.j2`, and the clab template set never reads
  them. Twinlab is clab-only, so these keys change nothing about a deployed lab — the same
  category as `tc:` and `tools:`, not a coverage gap. (Container-side sizing for the
  vrnetlab platform is a clab `env`/kind concern, not a netlab node attribute.)
- **Link `tc:`** — DECIDED 2026-08-05: the PUT now **rejects** it (gap 1, 422
  `unsupported_directive`), so it is in exactly the same category as `tools:` below —
  permanently B, and typing it would be UI for a key that cannot be saved. Reopen only if
  the post-v1.0 revisit honors it.
- **`tools:` and `validate:`** — the PUT rejects `tools:` outright (422
  `unsupported_directive`, gap 2) and Twinlab runs its own test suites. Permanently B.
  *(Adjacent and out of scope: the builder could warn on backend-rejected keys before the
  save round-trip.)*

### 6.4.2 Live, but a typed control would add nothing over the YAML

The criterion that replaces "no demand": **promote when the control does something the
extras editor cannot** — fix a lie, model a relationship, offer an enum or picker, grey by
the device catalog. A scalar with no validation beyond its type is equally editable either
way, and typing it only adds a shape we then owe compatibility to.

- **Node `id`, `router_id`, `mtu`, `unmanaged`, `skip_config`** — all live under clab, all
  plain scalars. A number field for `id` is not better than `id: 7`.
- **`plugin:`** — a list of strings whose whole purpose is to inject attributes that stay
  extras regardless. The list control would type the container and nothing it contains.

### 6.4.3 Live and worth typing, but too large to design before a tag

- **`vlans:` + the vlan module's semantics** — access/trunk/native propagation, a VLAN
  palette, and canvas meaning for vlan-member links. Genuinely valuable and genuinely
  netlab's most complex module; the exclusion is size and design risk immediately before a
  release, not lack of interest. Presence-only via Class 1 is what v1.0 gets, and a
  vlan lab still parses fully typed apart from the `vlans:` block and per-link vlan
  attributes.
- **`addressing:` / `prefix:` pools** — the strongest post-v1.0 candidate. Real under clab
  and central to how netlab users control an address plan, but it needs a design answer
  first: the backend re-pins `addressing.mgmt` on every PUT, so the editor must own the
  non-mgmt pools while showing the mgmt one as backend-managed.
- **`components:`/`include:` see-through** — large; Tier A already shipped the minimum (the
  endpoint-name rule plus the device-blocker waiver), so a components document parses and
  saves today.

## 6.5 Sizing and order

Seven frontend commits; each extends `pnpm check:build-doc` (36 checks today) and each
keeps the round-trip invariant `parse(emit(doc)) == doc`.

1. Module vocabulary + per-device fallback lists + offer set *(Class 1)*
2. Per-subkey splits: bgp, mpls, vrfs, groups *(Class 2)*
3. Link fields: prefix, bandwidth, mtu; self-link hint reads typed *(Classes 3–4)*
4. Endpoint fields: ipv4, ipv6, ifname *(Class 3)*
5. Node fields: loopback, config *(Class 3)*
6. Node `box`/`group`/`role` *(Class 5)*
7. Docs + memory

Order matters only for 1 before 2 (the vocabulary decides what `modulesShape` accepts) and
3 before 4 (both touch the link inspector).

**Verification** — the same shape the Tier A batch used, which is what made it trustworthy:
the harness checks under plain node; all four `examples/` definitions parsing and re-emitting
byte-stably; a real config-import output opened in the builder and saved unchanged (the F2
proof); and a `netlab create` over each emitted document, because the round-trip invariant
proves we did not lose the user's YAML, not that netlab likes it. Class 5's `group:`
normalization additionally needs the link-group treatment — the expanded topology
byte-identical before and after the rewrite.

## 6.6 Decisions

Reviewed 2026-08-05. **Classes 1–4 APPROVED**; the exclusion list was sent back because it
rested on our own usage as a demand signal, and the re-analysis (§6.4, Class 5) is the
result. Answers to the calls the review raised:

1. **The slate** — Classes 1–4 in. Class 5 follows from the re-analysis and is
   RECOMMENDED, not yet approved: it fixes two cases where the builder displays something
   untrue (`box`, `group`) plus one enum (`role`).
2. **`eigrp`** — in the parse vocabulary, out of the checkbox offer: a module list must
   never demote, and a permanently-greyed box for a device set that cannot run it is
   noise. Asymmetry is the honest shape.
3. **Presence-only for `vlan`/`vxlan`/`evpn`** — honest. The checkbox states what the
   document says; the dry `netlab create` remains the judge of whether the result is
   deployable, exactly as for every other module.
4. **Class 2's blast radius** — accepted. It re-partitions the typed/extras boundary for
   four keys, so every stored definition using them re-partitions on next parse; lossless,
   round-trip-guarded, and it is the largest behavioural change in the slate.
5. **Sequencing** — full slate, ahead of Playwright.

## 6.7 As shipped · 2026-08-05

All five classes, six frontend commits, no contract or backend change. The
harness went from 36 checks to **90**.

| Class | Commit |
|---|---|
| 1 · module vocabulary | the builder's module vocabulary is netlab's whole module set |
| 2 · subkey splits | bgp/mpls per subkey; vrf declarations and groups per entry |
| 3–4 · link fields | the link's prefix, bandwidth and mtu |
| 3 · endpoint fields | the endpoint's ifname, ipv4 and ipv6 |
| 3 · node fields | the node's loopback pin and config templates |
| 5 · re-analysis | the node's box, role and group |

**Live verification.** Both spellings of six documents were created under
netlab 26.07 **in the same directory** (netlab derives the lab name from it and
records the input path, so separate directories diff on the harness rather than
on the documents) and their expanded topologies compared:

- **byte-identical**: `box`, `role`, the merged `bgp`/`mpls` mappings, the vrf
  attribute split beside a groups-level `_auto_create`, and config import's
  link shape (typed endpoint `ipv4`/`ifname`, `ipv4: false`, `prefix: false`,
  `bandwidth`, `mtu`, node `loopback`).
- **one key different**: the node-`group` fold. netlab keeps a vestigial
  `group: [core]` on the node's own dict, which the folded document does not
  carry. Everything else matches, **the generated Ansible inventory is
  identical** — same `core` group, same members, same group_vars — and no
  netlab code reads a node-level `group` after expansion (`augment/groups.py`
  consumes it during expansion; the only other hits are link groups and a
  device-features `group`). So the fold is behaviourally inert. Its one visible
  cost: `node.group` leaves the fact namespace, where it sat in `_extras` — the
  tier that promises nothing by construction (delta 26).

  This is the one place the slate did not meet the bar §6.5 set for it
  ("byte-identical expanded topology", the link-group standard).
  **ACCEPTED 2026-08-05** — the delta is a key netlab writes and nothing reads,
  against a Groups UI that otherwise understates membership whenever a lab
  spells it node-side. The alternative was keeping the node-side spelling typed
  instead of folding, which would have given membership two sources of truth in
  the UI; that is the fix to revisit if the vestigial key ever turns out to
  matter.

Three test topologies of mine were wrong before they were right, and each was
a fact worth keeping: a group granting `bgp` without an AS fails for BOTH
spellings (not a fold bug — my `tail` had hidden the matching failure);
**netlab rejects a node carrying both `box` and `image`** outright, since the
early return on `box` leaves the `image` key it would otherwise consume; and a
P router inheriting a global `vrf` module crashes netlab itself inside
`mpls.node_adjust_mplsvpn`.
