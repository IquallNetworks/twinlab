// Round-trip checks for lib/build-doc.ts — `pnpm test`
// (or `pnpm check:build-doc` for just this file).
//
// The parser/emitter is the one piece of the frontend with real invariants:
// parse(emit(doc)) == doc, and every netlab spelling landing in exactly one
// of the typed core or the extras. Ported verbatim from
// scripts/check-build-doc.mjs when vitest arrived (2026-08-12) — the
// assertions are unchanged, the vite-bundle-then-import arrangement is gone.
// Kept as .mjs for the same reason as test-suite-model.test.mjs: gate checks
// deliberately feed the parser malformed input.
//
// Checks are (name, fn) pairs; fn returns null when it passes or a problem
// string when it does not, so a failure explains itself.

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { expect, it } from 'vitest'

import { buildDocEquals, emitBuildDoc, parseBuildDoc } from '@/lib/build-doc'

/** The old runner's contract, verbatim: a check returns a problem string or
 * something falsy. A throw is a failure either way — vitest reports it. */
function check(name, fn) {
  it(name, () => {
    const problem = fn()
    if (problem) expect.fail(String(problem))
  })
}

/** parse -> emit -> parse must yield an equal doc. Returns a problem or null. */
function roundTrip(yaml, devices) {
  const first = parseBuildDoc(yaml, devices)
  if (!first.ok) return `parse gated: ${first.reasons.join(' | ')}`
  const emittedYaml = emitBuildDoc(first.doc)
  if (!emittedYaml.ok) return `emit blocked: ${emittedYaml.problems.join(' | ')}`
  const second = parseBuildDoc(emittedYaml.yaml, devices)
  if (!second.ok) return `re-parse gated: ${second.reasons.join(' | ')}`
  if (!buildDocEquals(first.doc, second.doc)) {
    return `not doc-equal after round-trip\n--- emitted ---\n${emittedYaml.yaml}`
  }
  return null
}

function parsed(yaml, devices) {
  const result = parseBuildDoc(yaml, devices)
  if (!result.ok) throw new Error(`parse gated: ${result.reasons.join(' | ')}`)
  return result.doc
}

function emitted(yaml, devices) {
  const result = emitBuildDoc(parsed(yaml, devices))
  if (!result.ok) throw new Error(`emit blocked: ${result.problems.join(' | ')}`)
  return result.yaml
}

function gates(yaml, needle, devices) {
  const result = parseBuildDoc(yaml, devices)
  if (result.ok) return 'expected a gate, parsed fine'
  return result.reasons.some((r) => r.includes(needle))
    ? null
    : `expected a reason containing "${needle}", got: ${result.reasons.join(' | ')}`
}

// The known-device list the parse gate uses — mirrors the supported set, i.e.
// FALLBACK_DEVICE_CATALOG in src/lib/device-catalog.ts. It had drifted: bird and
// dnsmasq were admitted 2026-08-04 and never added here.
const DEV = ['vyos', 'linux', 'frr', 'routeros7', 'bird', 'dnsmasq']


// ---------------------------------------------------------------- regression
// The repo's own examples must keep round-tripping.
const EXAMPLES = fileURLToPath(new URL('../../../examples/', import.meta.url))
for (const file of ['mpls-l3vpn.yml', 'campus-lan.yml', 'mixed-nos.yml']) {
  check(`example ${file}`, () => roundTrip(readFileSync(`${EXAMPLES}${file}`, 'utf8'), DEV))
}

// ------------------------------------------------------------------- names
check('hyphenated node names parse', () =>
  roundTrip(
    `defaults.device: vyos\nnodes:\n  core-r1:\n  core-r2:\nlinks:\n- [core-r1, core-r2]\n`,
    DEV,
  ),
)

check('hyphenated names never emit the terse string form', () => {
  const out = emitted(`defaults.device: vyos\nnodes:\n  core-r1:\n  core-r2:\nlinks:\n- [core-r1, core-r2]\n`, DEV)
  return out.includes('core-r1-core-r2') ? `emitted the ambiguous string form:\n${out}` : null
})

check('plain names still emit the terse string form', () => {
  const out = emitted(`defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- [r1, r2]\n`, DEV)
  return out.includes('r1-r2') ? null : `expected the terse form, got:\n${out}`
})

check('name over 16 chars gates', () =>
  gates(`defaults.device: vyos\nnodes:\n  abcdefghijklmnopq:\n`, 'max 16', DEV),
)

check('16-char name is fine', () =>
  roundTrip(`defaults.device: vyos\nnodes:\n  abcdefghijklmnop:\n`, DEV),
)

// ------------------------------------------------------------- nodes forms
check('nodes as a list of dicts', () =>
  roundTrip(`nodes:\n- name: r1\n  device: vyos\n- name: r2\n  device: frr\n  mtu: 1500\nlinks:\n- r1-r2\n`, DEV),
)

check('nodes list-of-dicts keeps attributes', () => {
  const doc = parsed(`nodes:\n- name: r1\n  device: vyos\n  mtu: 1500\n`, DEV)
  const node = doc.nodes[0]
  if (node.name !== 'r1' || node.device !== 'vyos') return `node core wrong: ${JSON.stringify(node)}`
  return node.extras && node.extras.mtu === 1500 ? null : `mtu lost: ${JSON.stringify(node)}`
})

check('nodes list entry without a name gates', () =>
  gates(`nodes:\n- device: vyos\n`, 'name', DEV),
)

// ------------------------------------------------------------- link forms
check('list-form link with dict members', () =>
  roundTrip(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- [r1, {node: r2, ifname: eth9}]\n`,
    DEV,
  ),
)

check('list-form dict member keeps endpoint attributes', () => {
  const doc = parsed(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- [r1, {node: r2, ifname: eth9}]\n`,
    DEV,
  )
  const link = doc.links[0]
  const b = link.b
  // ifname is a typed endpoint field since the Tier B batch.
  return b.node === 'r2' && b.ifname === 'eth9'
    ? null
    : `endpoint attributes lost: ${JSON.stringify(link)}`
})

check('list-form member without a node gates', () =>
  gates(`defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- [r1, {ifname: eth9}]\n`, 'node', DEV),
)

// -------------------------------------------------------- dict-of-lists
const DICT_OF_LISTS = `defaults.device: vyos
nodes:
  r1:
  r2:
  r3:
links:
  core:
  - r1-r2
  access:
  - r2-r3
`
check('dict-of-lists links round-trip', () => roundTrip(DICT_OF_LISTS, DEV))

check('dict-of-lists keeps its list names', () => {
  const out = emitted(DICT_OF_LISTS, DEV)
  return out.includes('core:') && out.includes('access:')
    ? null
    : `list names lost on emit:\n${out}`
})

check('dict-of-lists list order is preserved', () => {
  const doc = parsed(DICT_OF_LISTS, DEV)
  const names = doc.links.map((l) => l.listName)
  return JSON.stringify(names) === JSON.stringify(['core', 'access'])
    ? null
    : `list names: ${JSON.stringify(names)}`
})

// ------------------------------------------------------------ link groups
const LINK_GROUP = `defaults.device: vyos
nodes:
  r1:
  r2:
  r3:
links:
- group: core
  mtu: 9000
  members:
  - r1-r2
  - r2-r3
`
check('link group expands on parse', () => {
  const doc = parsed(LINK_GROUP, DEV)
  if (doc.links.length !== 2) return `expected 2 expanded links, got ${doc.links.length}`
  // mtu is a typed link attribute since the Tier B batch.
  return doc.links.every((l) => l.mtu === 9000)
    ? null
    : `group data not copied down: ${JSON.stringify(doc.links)}`
})

check('expanded link group round-trips (expanded)', () => roundTrip(LINK_GROUP, DEV))

check('member data wins over group data', () => {
  const doc = parsed(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- group: core\n  mtu: 9000\n  members:\n  - r1:\n    r2:\n    mtu: 1500\n`,
    DEV,
  )
  return doc.links[0].mtu === 1500 ? null : `merge order wrong: ${JSON.stringify(doc.links[0])}`
})

// ------------------------------------------------------------- self-links
check('self-link parses', () => {
  const doc = parsed(`defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- [r1, r1]\n- r1-r2\n`, DEV)
  const link = doc.links[0]
  return link.kind === 'p2p' && link.a.node === 'r1' && link.b.node === 'r1'
    ? null
    : `self-link wrong: ${JSON.stringify(link)}`
})

check('self-link round-trips', () =>
  roundTrip(`defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- [r1, r1]\n- r1-r2\n`, DEV),
)

check('bare self-link never emits the string form', () => {
  const out = emitted(`defaults.device: vyos\nnodes:\n  r1:\nlinks:\n- [r1, r1]\n`, DEV)
  return out.includes('r1-r1') ? `emitted an ambiguous self string form:\n${out}` : null
})

check('attributed self-link emits the interfaces form', () => {
  const src = `defaults.device: vyos
nodes:
  r1:
links:
- interfaces:
  - node: r1
    ifname: eth1
  - node: r1
    ifname: eth2
  mtu: 1500
`
  const problem = roundTrip(src, DEV)
  if (problem) return problem
  const out = emitted(src, DEV)
  return out.includes('interfaces:') ? null : `expected the interfaces form, got:\n${out}`
})

check('self-link keeps per-endpoint attributes distinct', () => {
  const doc = parsed(
    `defaults.device: vyos\nnodes:\n  r1:\nlinks:\n- interfaces:\n  - node: r1\n    ifname: eth1\n  - node: r1\n    ifname: eth2\n`,
    DEV,
  )
  const link = doc.links[0]
  return link.a.ifname === 'eth1' && link.b.ifname === 'eth2'
    ? null
    : `endpoints merged: ${JSON.stringify(link)}`
})

check('self-LAN parses', () =>
  roundTrip(`defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- [r1, r1, r2]\n`, DEV),
)

// ------------------------------------------------------------- components
const COMPONENTS = `defaults.device: vyos
components:
  pod:
    nodes:
      leaf:
      spine:
nodes:
  p1:
    include: pod
  p2:
    include: pod
links:
- p1_leaf-p2_leaf
`
check('component-expanded endpoints parse', () => roundTrip(COMPONENTS, DEV))

check('include node needs no device', () => {
  const src = `components:\n  pod:\n    nodes:\n      leaf:\nnodes:\n  p1:\n    include: pod\n`
  const result = emitBuildDoc(parsed(src, DEV))
  return result.ok ? null : `emit blocked: ${result.problems.join(' | ')}`
})

check('an endpoint with no matching include still gates', () =>
  gates(`defaults.device: vyos\nnodes:\n  r1:\nlinks:\n- r1-p9_leaf\n`, 'undeclared', DEV),
)

// ------------------------------------------------------- hierarchical groups
check('a group may be a member of another group', () => {
  const src = `defaults.device: vyos
nodes:
  r1:
  r2:
groups:
  edge:
    members: [r1, r2]
  everything:
    members: [edge]
`
  const problem = roundTrip(src, DEV)
  if (problem) return problem
  return null
})

check('an undeclared group member still blocks', () => {
  const doc = parsed(`defaults.device: vyos\nnodes:\n  r1:\ngroups:\n  edge:\n    members: [nope]\n`, DEV)
  const result = emitBuildDoc(doc)
  return result.ok ? 'expected an emit blocker' : null
})

// ----------------------------------------------------------------- modules
// The vocabulary is netlab's whole user-module set, so a module the inspector
// has no dedicated control for must no longer demote the list — which used to
// take the BGP/LDP/VRF controls with it (they gate on the typed list).
check('an exotic module keeps the list typed', () => {
  const doc = parsed(`defaults.device: vyos\nmodule: [ospf, isis]\nnodes:\n  r1:\n`, DEV)
  if (doc.extras.module !== undefined) return 'the module list landed in extras'
  return doc.modules.join(',') === 'ospf,isis' ? null : `got modules ${doc.modules.join(',')}`
})

check('an exotic module round-trips', () =>
  roundTrip(`defaults.device: vyos\nmodule: [ospf, isis]\nnodes:\n  r1:\n`, DEV),
)

check('typed protocol keys survive beside an exotic module', () => {
  const doc = parsed(
    `defaults.device: vyos\nmodule: [ospf, bgp, isis]\nbgp.as: 65000\nnodes:\n  r1:\n`,
    DEV,
  )
  return doc.bgpAs === 65000 ? null : `bgp.as did not stay typed (got ${doc.bgpAs})`
})

check('a node-level exotic module stays typed', () => {
  const doc = parsed(`defaults.device: frr\nnodes:\n  r1:\n    module: [ospf, stp]\n`, DEV)
  return doc.nodes[0].extras?.module === undefined ? null : 'the node module list landed in extras'
})

check('a module outside netlab still rides extras', () => {
  const doc = parsed(`defaults.device: vyos\nmodule: [ospf, nosuchmodule]\nnodes:\n  r1:\n`, DEV)
  return doc.extras.module !== undefined ? null : 'an unknown module name was typed'
})

check('a non-string module entry still rides extras', () => {
  const doc = parsed(`defaults.device: vyos\nmodule: [ospf, 7]\nnodes:\n  r1:\n`, DEV)
  return doc.extras.module !== undefined ? null : 'a non-string module entry was typed'
})

// ------------------------------------------------------------ subkey splits
// A sibling key must not drag a typed one into extras: `bgp: {as, router_id}`
// used to demote the `as` too.
check('bgp overflow keeps the as typed', () => {
  const doc = parsed(
    `defaults.device: vyos\nmodule: [bgp]\nbgp:\n  as: 65000\n  router_id: 10.0.0.1\nnodes:\n  r1:\n`,
    DEV,
  )
  if (doc.bgpAs !== 65000) return `bgp.as not typed (got ${doc.bgpAs})`
  const rest = doc.extras.bgp
  return rest && rest.router_id === '10.0.0.1' && rest.as === undefined
    ? null
    : `unexpected bgp extras: ${JSON.stringify(rest)}`
})

check('bgp overflow round-trips', () =>
  roundTrip(
    `defaults.device: vyos\nmodule: [bgp]\nbgp:\n  as: 65000\n  router_id: 10.0.0.1\nnodes:\n  r1:\n`,
    DEV,
  ),
)

check('bgp overflow emits ONE bgp mapping', () => {
  const yaml = emitted(
    `defaults.device: vyos\nmodule: [bgp]\nbgp:\n  as: 65000\n  router_id: 10.0.0.1\nnodes:\n  r1:\n`,
    DEV,
  )
  if (yaml.includes('bgp.as')) return `emitted a dotted key beside the mapping:\n${yaml}`
  return yaml.includes('as: 65000') && yaml.includes('router_id') ? null : yaml
})

check('a lone bgp.as still emits the dotted key', () => {
  const yaml = emitted(`defaults.device: vyos\nmodule: [bgp]\nbgp.as: 65000\nnodes:\n  r1:\n`, DEV)
  return yaml.includes('bgp.as: 65000') ? null : yaml
})

check('node bgp overflow keeps the as typed', () => {
  const doc = parsed(
    `defaults.device: vyos\nmodule: [bgp]\nnodes:\n  r1:\n    bgp:\n      as: 65001\n      rr: true\n`,
    DEV,
  )
  return doc.nodes[0].bgpAs === 65001 && doc.nodes[0].extras?.bgp?.rr === true
    ? null
    : `node bgp split wrong: ${JSON.stringify(doc.nodes[0])}`
})

check('node bgp overflow round-trips', () =>
  roundTrip(
    `defaults.device: vyos\nmodule: [bgp]\nnodes:\n  r1:\n    bgp:\n      as: 65001\n      rr: true\n`,
    DEV,
  ),
)

check('mpls overflow keeps ldp typed', () => {
  const doc = parsed(
    `defaults.device: vyos\nmodule: [mpls]\nmpls:\n  ldp: true\n  6pe: true\nnodes:\n  r1:\n`,
    DEV,
  )
  return doc.mplsLdp === true && doc.extras.mpls?.['6pe'] === true
    ? null
    : `mpls split wrong: ${JSON.stringify({ ldp: doc.mplsLdp, extras: doc.extras.mpls })}`
})

check('mpls overflow round-trips', () =>
  roundTrip(
    `defaults.device: vyos\nmodule: [mpls]\nmpls:\n  ldp: true\n  6pe: true\nnodes:\n  r1:\n`,
    DEV,
  ),
)

check('node mpls overflow round-trips', () =>
  roundTrip(
    `defaults.device: vyos\nmodule: [mpls]\nnodes:\n  r1:\n    mpls:\n      vpn: true\n      6pe: true\n`,
    DEV,
  ),
)

check('a non-mapping bgp value is an ordinary extra', () => {
  const doc = parsed(`defaults.device: vyos\nbgp: 65000\nnodes:\n  r1:\n`, DEV)
  return doc.extras.bgp === 65000 && doc.bgpAs === undefined ? null : 'unexpected split'
})

check('a non-mapping bgp value round-trips', () =>
  roundTrip(`defaults.device: vyos\nbgp: 65000\nnodes:\n  r1:\n`, DEV),
)

check('a non-numeric as stays in extras', () => {
  const doc = parsed(`defaults.device: vyos\nbgp:\n  as: "65000"\nnodes:\n  r1:\n`, DEV)
  return doc.bgpAs === undefined && doc.extras.bgp?.as === '65000' ? null : 'unexpected split'
})

// -------------------------------------------------------------- link fields
check('link prefix, bandwidth and mtu are typed', () => {
  const doc = parsed(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- r1:\n  r2:\n  prefix: 10.1.0.0/30\n  bandwidth: 100000\n  mtu: 9000\n`,
    DEV,
  )
  const link = doc.links[0]
  if (link.extras !== undefined) return `extras should be empty: ${JSON.stringify(link.extras)}`
  return link.prefix === '10.1.0.0/30' && link.bandwidth === 100000 && link.mtu === 9000
    ? null
    : `not typed: ${JSON.stringify(link)}`
})

check('link attributes round-trip', () =>
  roundTrip(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- r1:\n  r2:\n  prefix: 10.1.0.0/30\n  bandwidth: 100000\n  mtu: 9000\n`,
    DEV,
  ),
)

check('prefix false is the L2 spelling and round-trips', () => {
  const doc = parsed(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- r1:\n  r2:\n  prefix: false\n`,
    DEV,
  )
  if (doc.links[0].prefix !== false) return `prefix not typed: ${JSON.stringify(doc.links[0])}`
  return roundTrip(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- r1:\n  r2:\n  prefix: false\n`,
    DEV,
  )
})

check('the prefix dict form still rides extras', () => {
  const doc = parsed(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- r1:\n  r2:\n  prefix:\n    ipv4: 10.1.0.0/30\n    allocation: p2p\n`,
    DEV,
  )
  return doc.links[0].prefix === undefined && doc.links[0].extras?.prefix !== undefined
    ? null
    : 'the dict prefix was typed'
})

check('a bare link still emits the terse form', () => {
  const yaml = emitted(`defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- r1-r2\n`, DEV)
  return yaml.includes('- r1-r2') ? null : yaml
})

check('a link with only a prefix emits the dict form', () => {
  const yaml = emitted(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- r1:\n  r2:\n  prefix: false\n`,
    DEV,
  )
  return yaml.includes('prefix: false') && !yaml.includes('- r1-r2') ? null : yaml
})

// ---------------------------------------------------------- endpoint fields
// The shape config import emits for a mixed wire: one addressed end, one
// spelled `ipv4: false` so netlab does not invent an address for it.
const IMPORT_LINK = `provider: clab
nodes:
  r1:
    device: vyos
    loopback:
      ipv4: 10.0.0.1/32
  r2:
    device: vyos
links:
- r1:
    ipv4: 10.1.0.1/30
  r2:
    ipv4: false
  prefix: 10.1.0.0/30
`

check('endpoint ifname, ipv4 and ipv6 are typed', () => {
  const doc = parsed(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- r1:\n    ifname: eth9\n    ipv4: 10.1.0.1/30\n    ipv6: 2001:db8::1/64\n  r2:\n`,
    DEV,
  )
  const a = doc.links[0].a
  if (a.extras !== undefined) return `extras should be empty: ${JSON.stringify(a.extras)}`
  return a.ifname === 'eth9' && a.ipv4 === '10.1.0.1/30' && a.ipv6 === '2001:db8::1/64'
    ? null
    : `not typed: ${JSON.stringify(a)}`
})

check('an unaddressed endpoint keeps its explicit false', () => {
  const doc = parsed(IMPORT_LINK, DEV)
  return doc.links[0].b.ipv4 === false ? null : `lost: ${JSON.stringify(doc.links[0].b)}`
})

check("config import's link shape round-trips", () => roundTrip(IMPORT_LINK, DEV))

check('endpoint extras still ride beside the typed fields', () => {
  const doc = parsed(
    `defaults.device: vyos\nmodule: [ospf]\nnodes:\n  r1:\n  r2:\nlinks:\n- r1:\n    ipv4: 10.1.0.1/30\n    ospf.cost: 100\n  r2:\n`,
    DEV,
  )
  const a = doc.links[0].a
  return a.ipv4 === '10.1.0.1/30' && a.extras?.['ospf.cost'] === 100
    ? null
    : `split wrong: ${JSON.stringify(a)}`
})

check('a self-link keeps typed endpoint addresses distinct', () =>
  roundTrip(
    `defaults.device: vyos\nnodes:\n  r1:\nlinks:\n- interfaces:\n  - node: r1\n    ipv4: 10.1.0.1/30\n  - node: r1\n    ipv4: 10.1.0.2/30\n`,
    DEV,
  ),
)

// -------------------------------------------------------------- node fields
check('the loopback pin config import writes is typed', () => {
  const r1 = parsed(IMPORT_LINK, DEV).nodes[0]
  return r1.loopback?.ipv4 === '10.0.0.1/32' ? null : `not typed: ${JSON.stringify(r1)}`
})

check('node config templates are typed', () => {
  const doc = parsed(
    `defaults.device: vyos\nnodes:\n  r1:\n    config: [ imported/r1 ]\n`,
    DEV,
  )
  return doc.nodes[0].config?.[0] === 'imported/r1' && doc.nodes[0].extras === undefined
    ? null
    : `not typed: ${JSON.stringify(doc.nodes[0])}`
})

check('node loopback + config round-trip', () =>
  roundTrip(
    `defaults.device: vyos\nnodes:\n  r1:\n    loopback:\n      ipv4: 10.0.0.1/32\n    config: [ imported/r1 ]\n`,
    DEV,
  ),
)

check('a loopback pool spelling rides the loopback extras', () => {
  const doc = parsed(`defaults.device: vyos\nnodes:\n  r1:\n    loopback:\n      pool: core\n`, DEV)
  return doc.nodes[0].loopback?.extras?.pool === 'core' ? null : 'pool was lost or mistyped'
})

check('a boolean loopback stays a node extra', () => {
  const doc = parsed(`defaults.device: vyos\nnodes:\n  r1:\n    loopback: false\n`, DEV)
  return doc.nodes[0].extras?.loopback === false ? null : 'the bool form was typed'
})

check('a boolean loopback round-trips', () =>
  roundTrip(`defaults.device: vyos\nnodes:\n  r1:\n    loopback: false\n`, DEV),
)

// -------------------------------------------------- box / role / node group
// netlab: box and image are one setting and BOX WINS (augment/nodes.py:335).
check('box feeds the image field', () => {
  const doc = parsed(`defaults.device: vyos\nnodes:\n  r1:\n    box: my/vyos:1\n`, DEV)
  return doc.nodes[0].image === 'my/vyos:1' && doc.nodes[0].imageKey === 'box'
    ? null
    : `box not typed: ${JSON.stringify(doc.nodes[0])}`
})

check('box keeps its spelling on save', () => {
  const yaml = emitted(`defaults.device: vyos\nnodes:\n  r1:\n    box: my/vyos:1\n`, DEV)
  return yaml.includes('box: my/vyos:1') && !yaml.includes('image:') ? null : yaml
})

check('box round-trips', () =>
  roundTrip(`defaults.device: vyos\nnodes:\n  r1:\n    box: my/vyos:1\n`, DEV),
)

check('box wins over image, and the loser is kept', () => {
  const doc = parsed(
    `defaults.device: vyos\nnodes:\n  r1:\n    image: ignored:1\n    box: wins:1\n`,
    DEV,
  )
  const node = doc.nodes[0]
  return node.image === 'wins:1' && node.extras?.image === 'ignored:1'
    ? null
    : `wrong precedence: ${JSON.stringify(node)}`
})

check('box beside image round-trips', () =>
  roundTrip(`defaults.device: vyos\nnodes:\n  r1:\n    image: ignored:1\n    box: wins:1\n`, DEV),
)

check('a node role is typed and round-trips', () => {
  const doc = parsed(`defaults.device: vyos\nnodes:\n  r1:\n    role: host\n`, DEV)
  if (doc.nodes[0].role !== 'host') return `role not typed: ${JSON.stringify(doc.nodes[0])}`
  return roundTrip(`defaults.device: vyos\nnodes:\n  r1:\n    role: host\n`, DEV)
})

check('an unknown role stays an extra', () => {
  const doc = parsed(`defaults.device: vyos\nnodes:\n  r1:\n    role: nonsense\n`, DEV)
  return doc.nodes[0].extras?.role === 'nonsense' ? null : 'an invalid role was typed'
})

// netlab appends a node's own `group:` to that group's members
// (augment/groups.py:405), so the builder folds it in and re-emits it there.
const NODE_GROUP = `defaults.device: vyos
groups:
  core:
    config: [ mpls_te ]
nodes:
  r1:
    group: [ core ]
  r2:
`

check('a node-side group becomes group membership', () => {
  const result = parseBuildDoc(NODE_GROUP, DEV)
  if (!result.ok) return `gated: ${result.reasons.join(' | ')}`
  const core = result.doc.groups.find((g) => g.name === 'core')
  if (core?.members.join(',') !== 'r1') return `members wrong: ${JSON.stringify(core)}`
  if (result.doc.nodes[0].extras?.group !== undefined) return 'the node kept a group extra'
  return result.notices.some((n) => n.includes('group membership'))
    ? null
    : `expected a notice, got: ${result.notices.join(' | ')}`
})

check('a node-side group round-trips once folded', () => roundTrip(NODE_GROUP, DEV))

check('a node-side group creates the group when undeclared', () => {
  const doc = parsed(`defaults.device: vyos\nnodes:\n  r1:\n    group: [ edge ]\n`, DEV)
  const edge = doc.groups.find((g) => g.name === 'edge')
  return edge?.members.join(',') === 'r1' ? null : `group not created: ${JSON.stringify(doc.groups)}`
})

check('a non-list group value stays an extra', () => {
  const doc = parsed(`defaults.device: vyos\nnodes:\n  r1:\n    group: core\n`, DEV)
  return doc.nodes[0].extras?.group === 'core' ? null : 'a scalar group was folded'
})

// ------------------------------------------------------------- vrfs, groups
const VRF_ATTRS = `defaults.device: vyos
module: [vrf]
vrfs:
  vpn_a:
    rd: "65000:1"
  vpn_b:
nodes:
  pe1:
    vrfs:
      vpn_a: { loopback: true }
`

check('an attributed vrf keeps every declaration typed', () => {
  const doc = parsed(VRF_ATTRS, DEV)
  const names = doc.vrfs.map((v) => v.name).join(',')
  if (names !== 'vpn_a,vpn_b') return `declarations lost: ${names}`
  return doc.vrfs[0].extras?.rd === '65000:1' ? null : 'rd did not ride the declaration'
})

check('an attributed vrf round-trips', () => roundTrip(VRF_ATTRS, DEV))

check('node vrf membership survives an attributed vrf', () => {
  const doc = parsed(VRF_ATTRS, DEV)
  return doc.nodes[0].vrfs?.vpn_a?.loopback === true ? null : 'membership was not typed'
})

check('node vrf attributes ride beside the typed loopback', () => {
  const doc = parsed(
    `defaults.device: vyos\nmodule: [vrf]\nvrfs:\n  vpn_a:\nnodes:\n  pe1:\n    vrfs:\n      vpn_a: { loopback: true, export: [ "65000:2" ] }\n`,
    DEV,
  )
  const membership = doc.nodes[0].vrfs?.vpn_a
  return membership?.loopback === true && membership.extras?.export !== undefined
    ? null
    : `unexpected membership: ${JSON.stringify(membership)}`
})

check('node vrf attributes round-trip', () =>
  roundTrip(
    `defaults.device: vyos\nmodule: [vrf]\nvrfs:\n  vpn_a:\nnodes:\n  pe1:\n    vrfs:\n      vpn_a: { loopback: true, export: [ "65000:2" ] }\n`,
    DEV,
  ),
)

const GROUPS_AUTO = `defaults.device: vyos
groups:
  _auto_create: true
  core:
    members: [ r1 ]
nodes:
  r1:
`

check('a groups-level setting no longer hides the groups', () => {
  const doc = parsed(GROUPS_AUTO, DEV)
  if (doc.extras.groups !== undefined) return 'the whole groups key went to extras'
  if (doc.groups.length !== 1) return `expected 1 group, got ${doc.groups.length}`
  return doc.groupsExtras?._auto_create === true ? null : 'the setting was lost'
})

check('a groups-level setting round-trips', () => roundTrip(GROUPS_AUTO, DEV))

check('a non-mapping groups value still rides extras whole', () => {
  const doc = parsed(`defaults.device: vyos\ngroups: [core]\nnodes:\n  r1:\n`, DEV)
  return doc.extras.groups !== undefined ? null : 'expected the whole key in extras'
})

// ---------------------------------------------------------- non-regressions
check('unknown device still gates', () =>
  gates(`nodes:\n  r1:\n    device: nosuchos\n`, 'catalog', DEV),
)

check('dict-form link still parses', () =>
  roundTrip(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- r1:\n    ifname: eth5\n  r2:\n  mtu: 1500\n`,
    DEV,
  ),
)

check('stub link still parses', () =>
  roundTrip(`defaults.device: vyos\nnodes:\n  r1:\nlinks:\n- r1:\n`, DEV),
)

check('interfaces mixed with node keys still gates', () =>
  gates(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- interfaces:\n  - node: r1\n  r2:\n`,
    'mixes',
    DEV,
  ),
)

check('2-member LAN still blocks at emit', () => {
  const doc = parsed(`defaults.device: vyos\nnodes:\n  r1:\n  r2:\n  r3:\nlinks:\n- [r1, r2, r3]\n`, DEV)
  doc.links[0].members = doc.links[0].members.slice(0, 2)
  return emitBuildDoc(doc).ok ? 'expected an emit blocker' : null
})
