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
