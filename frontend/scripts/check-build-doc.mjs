// Round-trip checks for lib/build-doc.ts — `pnpm check:build-doc`.
//
// The parser/emitter is the one piece of the frontend with real invariants
// (parse(emit(doc)) == doc, and every netlab spelling landing in exactly one
// of the typed core or the extras), and the frontend has no test runner. So
// this bundles the module — it is deliberately pure: no React, no `@/` alias,
// no zod — with the vite already in devDependencies, and exercises it under
// plain node. Adding a test runner would replace this wholesale; until then it
// is the parser's only regression net.
//
// Checks are (name, fn) pairs; fn returns null when it passes or a problem
// string when it does not, so a failure explains itself.

import { mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { build } from 'vite'

// Output goes under node_modules so the bundle's `yaml` import resolves the
// same way the app's does.
const outDir = mkdtempSync(join((mkdirSync('node_modules/.tmp', { recursive: true }), 'node_modules/.tmp'), 'build-doc-'))
try {
  await build({
    configFile: false,
    logLevel: 'error',
    build: {
      outDir,
      emptyOutDir: true,
      ssr: true,
      lib: { entry: 'src/lib/build-doc.ts', formats: ['es'], fileName: 'build-doc' },
    },
  })
} catch (err) {
  console.error('could not bundle src/lib/build-doc.ts:', err)
  process.exit(1)
}

const { parseBuildDoc, emitBuildDoc, buildDocEquals } = await import(
  pathToFileURL(resolve(outDir, 'build-doc.js')).href
)
rmSync(outDir, { recursive: true, force: true })

let pass = 0
const failures = []

function check(name, fn) {
  try {
    const problem = fn()
    if (problem) failures.push(`${name}: ${problem}`)
    else pass += 1
  } catch (err) {
    failures.push(`${name}: threw ${err && err.stack ? err.stack : err}`)
  }
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

const DEV = ['vyos', 'iol', 'linux', 'frr']


// ---------------------------------------------------------------- regression
// The repo's own examples must keep round-tripping.
const EXAMPLES = fileURLToPath(new URL('../../examples/', import.meta.url))
for (const file of ['mpls-l3vpn.yml', 'mpls-l3vpn.iol.yml', 'campus-lan.yml']) {
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
  roundTrip(`nodes:\n- name: r1\n  device: vyos\n- name: r2\n  device: iol\n  mtu: 1500\nlinks:\n- r1-r2\n`, DEV),
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

check('list-form dict member keeps endpoint extras', () => {
  const doc = parsed(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- [r1, {node: r2, ifname: eth9}]\n`,
    DEV,
  )
  const link = doc.links[0]
  const b = link.b
  return b.node === 'r2' && b.extras && b.extras.ifname === 'eth9'
    ? null
    : `endpoint extras lost: ${JSON.stringify(link)}`
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
  return doc.links.every((l) => l.extras && l.extras.mtu === 9000)
    ? null
    : `group data not copied down: ${JSON.stringify(doc.links)}`
})

check('expanded link group round-trips (expanded)', () => roundTrip(LINK_GROUP, DEV))

check('member data wins over group data', () => {
  const doc = parsed(
    `defaults.device: vyos\nnodes:\n  r1:\n  r2:\nlinks:\n- group: core\n  mtu: 9000\n  members:\n  - r1:\n    r2:\n    mtu: 1500\n`,
    DEV,
  )
  return doc.links[0].extras.mtu === 1500 ? null : `merge order wrong: ${JSON.stringify(doc.links[0])}`
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
  return link.a.extras.ifname === 'eth1' && link.b.extras.ifname === 'eth2'
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

console.log(`\n${pass} passed, ${failures.length} failed`)
for (const failure of failures) console.log(`\nFAIL ${failure}`)
process.exit(failures.length === 0 ? 0 : 1)
