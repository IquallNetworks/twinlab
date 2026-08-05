# Pinning the fact namespace — analysis and design

Status: **APPROVED and SHIPPED 2026-08-05** (contract delta 26). This is the
pre-v1.0 decision reserved by contract delta 17's review resolution (a): the
test-suite template namespace is netlab's RAW node dict, *provisional and
deliberately unpinned*, with `GET /labs/{name}/facts` shipped as the insulation
layer for exactly this moment.

**The maintainer's direction (2026-08-05), which §5 onward works out:** a
stable promised core, and a well-documented **`_extras` namespace holding every
other key** — internal keys included — for which no promises are made. The
frontend surfaces all of it, extras clearly marked unstable. (This supersedes
the first draft's option B, which pinned paths in place and left the remainder
mixed in beside them; the partitioned form puts the stability signal in the
path itself — a suite rendering `{{ node._extras.mtu }}` is visibly leaning on
unstable ground at every use site.)

## 1. What the namespace is today

One artifact serves every surface. `create_clab_topology` extracts the expanded
topology's `nodes` as raw dicts (`_extract_node_facts`, shape-checked one level
deep — "everything below is netlab's to define"), persisted as a regenerable
JSONB cache beside the link table. Consumers:

- **Template rendering** (`services/validation.py`): `node` / `nodes.<name>`
  resolve to exactly these dicts; one filter, `address` (strip a CIDR's prefix
  length). Sandboxed, StrictUndefined.
- **`GET /labs/{name}/facts`** — the same dicts on the wire, documented as
  "exactly what `nodes.<n>` resolves to". The two surfaces are one namespace
  and must stay identical.
- **PUT dry-render** — suites validate against these dicts at author time.
- Internal (not contract): config-import reads `loopback` and interface
  addresses; validation's device-keyed dispatch reads `device`. Neither
  constrains this decision — both are backend-internal uses of
  `ClabArtifacts.node_facts`.

## 2. The observed namespace (evidence)

Fourteen nodes across two labs on netlab **26.07**: `mixed-nos` (deployed —
vyos, frr, routeros7, bird, dnsmasq, linux ×2; ospf across four families) and a
dry-created `mpls-l3vpn` throwaway (vyos ×7; bgp/mpls/ldp/vrf). Raw dumps in
the session scratchpad; re-derive with `client.facts()` any time.

**Universal top-level keys** (every node, every device):
`name`, `id`, `device`, `hostname` (the `clab-<lab>-<node>` container name),
`box` (image), `mgmt` (`{ifname, ipv4, mac}`), `interfaces`, `af`, `module`,
`clab` (provider subtree: `kind`, `binds`).

**Conditional top-level keys** — the variance that makes naive pinning wrong:

| key | present | absent |
|---|---|---|
| `loopback` | routers (vyos, frr, chr, the PEs) | `role: host` nodes and daemons — **bird gets a `router_id` but NO loopback interface** (the documented mixed-nos semantics) |
| `role` | hosts/daemons (`host`) | routers (absence means router) |
| `router_id` (top-level) | nodes that need one without a loopback to derive it from (bird) | vyos, chr, … |
| `mtu` (node-level) | vyos, frr, daemons | **chr** |
| protocol subtrees | per `module`: `ospf`, `bgp`, `ldp`, `mpls`, `vrf`+`vrfs`, `dhcp`, `routing` | — |

**Interface entries** (`interfaces[]`): `ifname`, `ifindex`, `linkindex`,
`type`, `name` (the link's name), `ipv4`, `neighbors[]` (`{node, ifname,
ipv4}`), plus conditionals: `mtu`, `bridge` + `gateway` (LAN members),
`virtual_interface` (loopback-type stubs), `clab.name` (renaming kinds — CHR's
`ether2` ↔ `eth1`), per-module overlays (`interfaces[].ospf.{area,
network_type, passive}`).

**netlab-internal keys**, underscore-prefixed by netlab's own convention (the
same convention delta 14 already ruled on for `_linkname`):

- top-level: `_daemon`, `_daemon_config`, `_daemon_parent` (daemons),
  `_node_config` (daemons, frr, linux)
- nested: `bgp.neighbors[]._source_intf` (a full embedded interface dict),
  `ospf.areas[]._area_int`
- plus `netlab_ansible_skip_module` — not underscore-spelled but pure Ansible
  plumbing.

Nothing in the backend reads any of these (verified by grep).

## 3. Consumption evidence

Every template expression shipped in the two example suites:

- `nodes.<n>.ospf.router_id` (×6 — the mixed-nos suite's four flavours)
- `nodes.<n>.loopback.ipv4 | address` (×5)
- `nodes.<n>.vrfs.vpn_a.loopback_address.ipv4 | address` (×4)

The delta 17 contract text additionally names `mgmt.ipv4`,
`interfaces[].{ifname, ipv4, neighbors}` and `vrfs.<vrf>.loopback` as intended
usage. That is the whole known consumption surface: **identity + addressing +
neighbor topology + protocol identifiers.** No consumer reaches for `box`,
`clab`, or any internal key.

## 4. Stability

The node attribute namespace is what netlab's **own device config templates
render against** — `loopback.ipv4`, `bgp.neighbors`, `vrfs.<v>.rd` appear
throughout netlab's packaged Jinja2. netlab cannot churn these names without
rewriting its own templates for every device, so the core has strong inertia
and is documented in netlab's node/module references. The underscore keys carry
no such promise — they are transformation bookkeeping. `box` and `clab` are
provider-flavored (the `clab` subtree literally mirrors provider internals).

## 5. The decided model: promised core + `_extras` partition

Each node's facts are **partitioned**: a pinned member stays in place with a
pinned shape; every other key moves verbatim under `_extras`. No key is ever
dropped — internal keys (netlab's `_`-prefixed bookkeeping,
`netlab_ansible_skip_module`) ride in `_extras` too, doubly unstable but
visible. The promise is exactly the partition: what sits outside `_extras` is
stable Twinlab contract (Twinlab adapts — shim or contract errata — if a
netlab upgrade moves a source key; the drift guard is the teeth); what sits
inside `_extras` is netlab-shaped and may change or vanish with any netlab
release.

**The partition is per-object, not top-level-only.** Every dict the pin
recognizes as an object carries its own `_extras` (omitted when empty), so the
rule reaches inside subtrees: `ospf.router_id` is pinned in place while
`ospf.areas` lands in `ospf._extras.areas`, and an interface entry keeps
`ifname`/`ipv4` in place while its `bridge`/`gateway`/`mtu` land in that
entry's `_extras`. Top-level-only partitioning was considered and rejected: it
would leave unpinned members sitting unmarked *inside* pinned subtrees, which
is precisely the ambiguity this model exists to kill. Lists are never
index-mirrored — a list entry is an object with its own `_extras`.

Recognized objects (the classifier is this list): the node itself; `mgmt`;
`loopback`; `interfaces[i]`; `interfaces[i].neighbors[j]`;
`interfaces[i].ospf`; `ospf`; `bgp`; `bgp.neighbors[i]`; `ldp`; `vrfs.<name>`;
`vrfs.<name>.loopback_address`. Below any unpinned key, content is verbatim —
the partition never descends into `_extras`.

Properties (all tested at implementation):
- **Partition invariant**: every raw key lands in exactly one place —
  reassembly (merge each object's `_extras` back in place) reproduces the raw
  dict. Dict *equality*, not byte equality: key ORDER is not restored and is
  deliberately not part of the promise. Same invariant style as
  config-import's three-bucket partition and the build-doc round trip.
- **No shadowing**: a hypothetical netlab-supplied `_extras` key is itself
  unpinned, so it lands at `_extras._extras` — ours always wins the position.
- **Sandbox ergonomics verified live**: jinja2's SandboxedEnvironment blocks
  unsafe *object attributes*, not dict keys — `{{ node._extras.mtu }}` renders
  (attribute syntax falls through to `__getitem__`). Probed on 3.1.6.
- **Shipped suites unaffected**: every template expression in both example
  suites resolves inside the pinned core (§3), so nothing rewrites.

## 6. The pinned core (the per-object member lists)

`?` = present when the feature exists; absence is meaningful (bird's missing
`loopback` is a fact, not a gap). Everything not listed is that object's
`_extras`.

**Node** — always:
- `name: str` · `id: int` · `device: str` · `hostname: str` (container name)
- `role: str?` (absent = router)
- `af: {ipv4?: bool, ipv6?: bool}` · `module: [str]`
- to `_extras` (observed): `box`, `clab`, `mtu`, `router_id`, `mpls`, `dhcp`,
  `routing`, `_daemon*`, `_node_config`, `netlab_ansible_skip_module`

**`mgmt`** — `{ifname: str, ipv4?: str, ipv6?: str, mac?: str}` (bare IPs, no
prefix). **`loopback?`** — `{ifname: str, ipv4?: str, ipv6?: str}` (CIDR form;
its interface-entry bookkeeping — `ifindex`, `type`, `virtual_interface`,
module overlays — is its `_extras`).

**`interfaces[i]`**:
- `ifname: str` (NOS-side name) · `ifindex: int` · `type: str` (presence
  pinned, vocabulary netlab's) · `linkindex?: int` · `name?: str` (link name)
- `ipv4?: str` / `ipv6?: str` (CIDR form)
- `neighbors: [{node: str, ifname: str, ipv4?: str, ipv6?: str}]`
- `ospf?: {area: str}` (the per-interface overlay; `network_type`/`passive` →
  its `_extras`)
- to `_extras` (observed): `mtu`, `bridge`, `gateway`, `virtual_interface`,
  `clab`

**Protocol subtrees** — pinned for the proven module set (the builder's typed
four); a subtree exists iff its module is on:
- `ospf: {router_id: str, area: str}`
- `bgp: {as: int, router_id: str, neighbors: [{name: str, as: int, type: str,
  ipv4?: str, vpnv4?: str}]}` (neighbor `activate`/`next_hop_self`/
  `_source_intf` → the entry's `_extras`)
- `ldp: {router_id: str}`
- `vrfs: {<vrf>: {rd: str, import: [str], export: [str],
  loopback_address?: {ipv4?: str, ipv6?: str}}}`

**The filter** — `address` (CIDR → bare address), already contract text.

Worked example — vyos1 (mixed-nos), partitioned:

```json
{
  "name": "vyos1", "id": 1, "device": "vyos",
  "hostname": "clab-mixed-nos-vyos1",
  "af": {"ipv4": true}, "module": ["ospf"],
  "mgmt": {"ifname": "eth0", "ipv4": "10.77.10.101", "mac": "ca:fe:00:01:00:00"},
  "loopback": {"ifname": "dum0", "ipv4": "10.0.0.1/32",
    "_extras": {"ifindex": 0, "neighbors": [], "type": "loopback",
                "virtual_interface": true, "ospf": {"area": "0.0.0.0", "passive": false}}},
  "interfaces": [
    {"ifname": "eth1", "ifindex": 1, "linkindex": 1, "type": "p2p",
     "name": "vyos-frr", "ipv4": "10.1.0.2/30",
     "neighbors": [{"node": "frr1", "ifname": "eth1", "ipv4": "10.1.0.1/30"}],
     "ospf": {"area": "0.0.0.0",
              "_extras": {"network_type": "point-to-point", "passive": false}},
     "_extras": {"mtu": 1500}}
  ],
  "ospf": {"router_id": "10.0.0.1", "area": "0.0.0.0",
           "_extras": {"af": {"ipv4": true},
                       "areas": [{"_area_int": 0, "area": "0.0.0.0", "kind": "regular"}]}},
  "_extras": {"box": "ghcr.io/sysoleg/vyos-container", "mtu": 1500,
              "clab": {"kind": "linux", "binds": [{"source": "/lib/modules", "target": "/lib/modules"}]}}
}
```

## 7. Mechanism (what implementation touches)

- **One pure partition function** (static schema walk over the recognized
  objects). The JSONB cache stays RAW — partition applies at the serve
  boundaries: the template render context, the PUT dry-render, and
  `GET /labs/{name}/facts`. Wire and render context stay identical (the
  standing invariant); internal consumers (config-import's `loopback` read,
  validation's `device` dispatch, the diff's address join) keep the raw shape
  — they all read pinned-core paths anyway, which independently corroborates
  the member lists. No migration, no cache versioning, no idempotency
  question.
- **Contract delta 26**: `LabFacts` / `TestCase` text loses PROVISIONAL; the
  pinned per-object member lists land as a contract appendix (precedent: the
  shipped-catalogs appendix). The partition is the wire-visible change.
- **Drift guard**: a backend test running the installed netlab over the
  `examples/` definitions and asserting every pinned path exists with the
  pinned shape in the partitioned output — a netlab upgrade that moves a
  pinned source key fails it loudly. Plus the reassembly round-trip test on
  captured fixtures.
- **Client**: `LabFacts.nodes` stays `dict[str, dict[str, object]]` — a fully
  typed facts model would freeze netlab's entire node schema, the opposite of
  insulation. Docstring mirrors only.
- **Frontend**: the FactsViewer already renders the full payload as JSON, so
  `_extras` arrives structurally marked; its dialog copy changes from
  "unpinned pre-v1.0" to the two-tier rule (outside `_extras` = stable
  contract; inside = netlab-shaped, no promises). Suite authoring needs
  nothing more — the path spelling carries the marker into every template.
- **Dev-phase note**: no stored real-world suites exist (the same ground the
  no-v1→v2-migration call stood on), and both example suites resolve entirely
  inside the core, so the partition breaks nobody.

## 8. As shipped (2026-08-05)

Approved as proposed — the per-object rule, the §6 member lists (including
`bgp.neighbors[].vpnv4` and `interfaces[].ospf.area`), and dialog copy plus the
structural marker for the frontend. Delta **26**.

Landed across backend (`services/fact_namespace.py` + the three serve
boundaries, 15 tests), client (`LabFacts` documents both tiers), frontend (the
FactsViewer teaches them) and blackbox (2 tests, one pinning the partition
itself). Backend 262 · client 62 · frontend typecheck/build/36 checks ·
**blackbox 141 passed + 1 opt-in skip, deploy-marked included**.

**Live verification on the deployed mixed-nos lab:**

- The partition is real on the wire across all six platforms — e.g. vyos1 keeps
  ten core keys with `box`/`clab`/`mtu` in `_extras`; `ospf` keeps
  `router_id`/`area` with `af`/`areas` beneath its own `_extras`; dns1's four
  netlab-internal `_daemon*`/`_node_config` keys are present-but-unpromised
  rather than dropped.
- **bird1 has no `loopback` and a `router_id` in `_extras`** — the pin made that
  asymmetry explicit instead of leaving a suite author to discover it.
- The shipped suites pass **9/9 unchanged**, and re-PUTting them exercised the
  dry-render gate against the partitioned namespace.
- Both directions of the tier boundary hold: `{{ node._extras.box }}` renders
  (unpromised is not unavailable), while `{{ node.box }}` is a 422
  `template_invalid` at PUT — the key exists in exactly one place, so the
  partition is enforcement, not decoration.

**The one consequence worth stating plainly:** a template that read an unpinned
key at its old path now fails — StrictUndefined makes it a 422 at PUT and an
`error` result at run time, never a silent empty string. Nothing in the repo or
in any stored suite did (dev phase, and both examples render core paths only),
which is exactly why this was the moment to do it.
