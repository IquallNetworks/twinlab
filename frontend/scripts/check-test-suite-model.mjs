// Checks for lib/test-suite-model.ts — `pnpm check:test-suites`.
//
// Same arrangement as check-build-doc.mjs, and for the same reason: the module
// is pure and the frontend has no test runner, so this bundles it with the
// vite already in devDependencies and exercises it under plain node.
//
// What it guards is narrower than build-doc's round-trip, because a suite's
// schema is CLOSED — there is no lossy emit to worry about. The invariant here
// is that the client-side gates AGREE with the server's: everything the PUT
// rejects must be an "error", and nothing the PUT accepts may be, or the
// builder would refuse a suite the contract allows.

import { mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

import { build } from 'vite'

const outDir = mkdtempSync(
  join((mkdirSync('node_modules/.tmp', { recursive: true }), 'node_modules/.tmp'), 'suite-model-'),
)

async function bundle(entry, fileName) {
  try {
    await build({
      configFile: false,
      logLevel: 'error',
      build: {
        outDir,
        emptyOutDir: false,
        ssr: true,
        lib: { entry, formats: ['es'], fileName },
      },
    })
  } catch (err) {
    console.error(`could not bundle ${entry}:`, err)
    process.exit(1)
  }
}

await bundle('src/lib/test-suite-model.ts', 'test-suite-model')
await bundle('src/lib/fact-completions.ts', 'fact-completions')
await bundle('src/lib/test-results.ts', 'test-results')

const {
  blankCase,
  blankSuite,
  blankTest,
  caseEntries,
  hasBlockingProblem,
  isDeviceKeyed,
  matcherKind,
  nameProblem,
  resolveTargets,
  toDeviceKeyed,
  toSharedCase,
  uniqueName,
  validateSuites,
  withMatcher,
} = await import(pathToFileURL(resolve(outDir, 'test-suite-model.js')).href)
const { completionRequest, factCompletions, factRoot } = await import(
  pathToFileURL(resolve(outDir, 'fact-completions.js')).href
)
const {
  formatElapsed,
  labValidation,
  matchesFilter,
  orphanedTests,
  outcomesByTest,
  readStatus,
  reportTally,
  rollUp,
  suiteStatus,
  tallyLine,
} = await import(pathToFileURL(resolve(outDir, 'test-results.js')).href)
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

// The lab the checks author against: a VyOS router, an FRR router and a linux
// host — chosen because their capabilities disagree in both directions.
const CTX = {
  nodes: ['r1', 'r2', 'h1'],
  deviceByNode: new Map([
    ['r1', 'vyos'],
    ['r2', 'frr'],
    ['h1', 'linux'],
  ]),
  capabilities: new Map([
    ['vyos', { cliMode: true, textfsm: true }],
    ['frr', { cliMode: true, textfsm: false }],
    ['linux', { cliMode: false, textfsm: true }],
  ]),
  // A nested group already FLATTENED, the way the server serves it.
  groups: new Map([
    ['core', ['r1', 'r2']],
    ['edge', ['h1']],
  ]),
}

function testOf(testCase, target = { nodes: ['r1'] }) {
  return {
    run: testCase,
    nodes: target.nodes ?? [],
    groups: target.groups ?? [],
    all_nodes: target.all_nodes ?? false,
    wait: target.wait ?? 0,
    description: '',
  }
}

function suiteOf(testCase, nodes = ['r1']) {
  const target = Array.isArray(nodes) ? { nodes } : nodes
  return { s: { stage: 'runtime', description: '', tests: { t: testOf(testCase, target) } } }
}

function problemsFor(testCase, nodes) {
  return validateSuites(suiteOf(testCase, nodes), CTX)
}

function errorsFor(testCase, nodes) {
  return problemsFor(testCase, nodes).filter((p) => p.severity === 'error')
}

// --- Names ---------------------------------------------------------------

check('name rule accepts the server charset', () => {
  for (const ok of ['smoke', 'a', 'ospf.full', 'a-b_c', '1st']) {
    if (nameProblem(ok) !== null) return `${ok} rejected: ${nameProblem(ok)}`
  }
  return null
})

check('name rule rejects what the server rejects', () => {
  for (const bad of ['', '-leading', '.dot', 'has space', 'a'.repeat(65)]) {
    if (nameProblem(bad) === null) return `${bad || '(empty)'} accepted`
  }
  return null
})

// --- Matchers ------------------------------------------------------------

check('matcherKind names exactly-one and refuses none or several', () => {
  if (matcherKind({ contains: 'x' }) !== 'contains') return 'single not detected'
  if (matcherKind({ compare: {} }) !== 'compare') return 'compare not detected'
  if (matcherKind({}) !== null) return 'empty should be null'
  if (matcherKind({ contains: 'a', matches: 'b' }) !== null) return 'two should be null'
  if (matcherKind(undefined) !== null) return 'undefined should be null'
  return null
})

check('withMatcher carries text between raw matchers only', () => {
  if (withMatcher({ contains: 'Full' }, 'matches').matches !== 'Full') return 'text not carried'
  if (withMatcher({ contains: 'Full' }, 'compare').contains != null) return 'contains survived'
  if (Object.keys(withMatcher({ compare: { a: 1 } }, 'contains')).length !== 1) {
    return 'switch left more than one matcher'
  }
  return null
})

// --- Case forms ----------------------------------------------------------

check('a case and a device-keyed map are discriminated by command', () => {
  if (isDeviceKeyed(blankCase())) return 'shared case read as keyed'
  if (!isDeviceKeyed({ vyos: blankCase() })) return 'keyed map read as shared'
  return null
})

check('caseEntries reports the shared case as device null', () => {
  const shared = caseEntries(blankCase())
  if (shared.length !== 1 || shared[0].device !== null) return 'shared entry wrong'
  const keyed = caseEntries({ vyos: blankCase(), frr: blankCase() })
  if (keyed.map((e) => e.device).join(',') !== 'vyos,frr') return 'keyed order/keys wrong'
  return null
})

check('converting between the run forms keeps the authored case', () => {
  const authored = { ...blankCase(), command: 'show version' }
  const keyed = toDeviceKeyed(authored, ['vyos', 'frr'])
  if (Object.keys(keyed).length !== 2) return 'expand did not seed every device'
  if (keyed.vyos.command !== 'show version') return 'expand lost the command'
  if (toSharedCase(keyed).command !== 'show version') return 'collapse lost the command'
  // Idempotent both ways.
  if (toSharedCase(authored) !== authored) return 'collapse of a shared case changed it'
  return null
})

// --- Gates that mirror the PUT ------------------------------------------

check('a blank suite is authorable but not yet saveable', () => {
  const problems = validateSuites({ s: blankSuite(['r1']) }, CTX)
  // The command is empty, so exactly that should block — nothing else.
  const fields = problems.filter((p) => p.severity === 'error').map((p) => p.field)
  if (fields.join(',') !== 'run.command') return `blocked on ${fields.join(',') || '(nothing)'}`
  return null
})

check('a complete case is clean', () => {
  const testCase = { command: 'ip -o link show lo', expect: { contains: 'UP' }, mode: 'shell', interactive: false }
  const problems = problemsFor(testCase)
  if (problems.length !== 0) return problems.map((p) => `${p.field}: ${p.message}`).join(' | ')
  return null
})

check('zero and two matchers both block', () => {
  const base = { command: 'true', mode: 'shell', interactive: false }
  if (errorsFor({ ...base, expect: {} }).length === 0) return 'zero matchers accepted'
  if (errorsFor({ ...base, expect: { contains: 'a', matches: 'b' } }).length === 0) {
    return 'two matchers accepted'
  }
  return null
})

check('compare and parse are required of each other, both ways', () => {
  const base = { command: 'true', mode: 'shell', interactive: false }
  if (errorsFor({ ...base, expect: { compare: { a: 1 } } }).length === 0) {
    return 'compare without parse accepted'
  }
  if (errorsFor({ ...base, expect: { contains: 'x' }, parse: 'json' }).length === 0) {
    return 'parse without compare accepted'
  }
  if (errorsFor({ ...base, expect: { compare: { a: 1 } }, parse: 'json' }).length !== 0) {
    return 'the legal pairing was blocked'
  }
  return null
})

check('a broken regex blocks, a valid one does not', () => {
  const base = { command: 'true', mode: 'shell', interactive: false }
  if (errorsFor({ ...base, expect: { matches: 'FULL/\\w+' } }).length !== 0) return 'valid regex blocked'
  if (errorsFor({ ...base, expect: { matches: '([' } }).length === 0) return 'broken regex accepted'
  return null
})

check('cli mode blocks on a device with no CLI — via the case OR the nodes', () => {
  const cliCase = { command: 'show version', expect: { contains: 'x' }, mode: 'cli', interactive: false }
  // Device-keyed: the case names its own device.
  const keyed = validateSuites(suiteOf({ linux: cliCase }, ['h1']), CTX)
  if (!keyed.some((p) => p.severity === 'error' && p.field.includes('mode'))) {
    return 'device-keyed cli on linux accepted'
  }
  // Shared: every TARGET node's device has to answer for it.
  if (errorsFor(cliCase, ['h1']).length === 0) return 'shared cli on a linux node accepted'
  if (errorsFor(cliCase, ['r1']).length !== 0) return 'cli on vyos blocked'
  return null
})

check('textfsm on a device without templates warns but does not block', () => {
  // FRR has a CLI but answers in JSON — no TextFSM set. The PUT accepts this
  // (it fails at RUN time), so the builder must not be stricter.
  const testCase = {
    command: 'show ip ospf neighbor',
    expect: { compare: { a: 1 } },
    parse: 'textfsm',
    mode: 'cli',
    interactive: false,
  }
  const problems = problemsFor(testCase, ['r2'])
  if (!problems.some((p) => p.severity === 'warning' && p.field.includes('parse'))) {
    return 'no warning raised'
  }
  if (hasBlockingProblem(problems)) return 'warning was treated as blocking'
  return null
})

check('an unknown node warns, and only when the lab has nodes', () => {
  const testCase = { command: 'true', expect: { contains: 'x' }, mode: 'shell', interactive: false }
  const known = problemsFor(testCase, ['nope'])
  if (!known.some((p) => p.severity === 'warning' && p.field === 'nodes')) return 'no warning'
  if (hasBlockingProblem(known)) return 'unknown node blocked the save'
  // A suite authored BEFORE the definition is legitimate — the server takes it.
  const bare = validateSuites(suiteOf(testCase, ['nope']), { ...CTX, nodes: [] })
  if (bare.length !== 0) return 'flagged a node on a lab with no nodes yet'
  return null
})

check('wait is bounded the way the server bounds it', () => {
  const testCase = { command: 'true', expect: { contains: 'x' }, mode: 'shell', interactive: false }
  const withWait = (wait) =>
    validateSuites(suiteOf(testCase, { nodes: ['r1'], wait }), CTX).filter(
      (p) => p.severity === 'error',
    )
  if (withWait(0).length !== 0) return '0 rejected'
  if (withWait(600).length !== 0) return '600 rejected'
  if (withWait(601).length === 0) return '601 accepted'
  if (withWait(-1).length === 0) return '-1 accepted'
  return null
})

check('an empty suite and an empty device-keyed run both block', () => {
  const empty = validateSuites({ s: { stage: 'runtime', description: '', tests: {} } }, CTX)
  if (!empty.some((p) => p.severity === 'error' && p.field === 'tests')) return 'empty suite accepted'
  const noCases = validateSuites(suiteOf({}, ['r1']), CTX)
  if (!noCases.some((p) => p.severity === 'error' && p.field === 'run')) {
    return 'empty device-keyed run accepted'
  }
  return null
})

check('a new test targets EVERY node, which is the edit-proof default', () => {
  const test = blankTest()
  if (!test.all_nodes) return 'a new test should target all nodes'
  if (test.nodes.length !== 0 || test.groups.length !== 0) return 'redundant explicit selectors'
  if (test.wait !== 0) return 'wait should default to a single attempt'
  return null
})

// --- Targeting (delta 32) ---

check('a nodes-only target resolves to exactly its nodes, in order', () => {
  // The compatibility line: every suite written before delta 32 is unchanged,
  // result order included.
  const got = resolveTargets(testOf(blankCase(), { nodes: ['h1', 'r1'] }), CTX.nodes, CTX.groups)
  if (got.join(',') !== 'h1,r1') return `got ${got.join(',')}`
  return null
})

check('all_nodes takes the lab in topology order', () => {
  const got = resolveTargets(testOf(blankCase(), { all_nodes: true }), CTX.nodes, CTX.groups)
  if (got.join(',') !== 'r1,r2,h1') return `got ${got.join(',')}`
  return null
})

check('a group plus named extras unions without duplicating', () => {
  const target = { groups: ['core'], nodes: ['h1', 'r1'] }
  const got = resolveTargets(testOf(blankCase(), target), CTX.nodes, CTX.groups)
  if (got.join(',') !== 'r1,r2,h1') return `got ${got.join(',')}`
  return null
})

check('an unknown group contributes nothing', () => {
  const target = { groups: ['gone'], nodes: ['r1'] }
  const got = resolveTargets(testOf(blankCase(), target), CTX.nodes, CTX.groups)
  if (got.join(',') !== 'r1') return `got ${got.join(',')}`
  return null
})

check('a test that targets nothing blocks the save', () => {
  const problems = validateSuites(suiteOf(blankCase(), { nodes: [] }), CTX)
  if (!problems.some((p) => p.severity === 'error' && /target something/.test(p.message))) {
    return 'an empty target was accepted'
  }
  return null
})

check('an unknown group warns without blocking', () => {
  const complete = { command: 'true', expect: { contains: 'x' }, mode: 'shell', interactive: false }
  const problems = validateSuites(suiteOf(complete, { groups: ['gone'] }), CTX)
  if (!problems.some((p) => p.severity === 'warning' && p.field === 'groups')) return 'no warning'
  // It also resolves to nothing, which is its own warning — but neither blocks:
  // the server accepts both, and the group may come back.
  if (hasBlockingProblem(problems)) return 'a group problem blocked the save'
  return null
})

check('cli mode is judged against the RESOLVED targets, not just `nodes`', () => {
  // The regression this guards: a group containing a linux host must veto cli
  // mode exactly as naming that host would.
  const cliCase = { command: 'show version', expect: { contains: 'x' }, mode: 'cli', interactive: false }
  const viaGroup = validateSuites(suiteOf(cliCase, { groups: ['edge'] }), CTX)
  if (!viaGroup.some((p) => p.severity === 'error' && p.field.includes('mode'))) {
    return 'a linux host reached through a group did not veto cli mode'
  }
  const allNodes = validateSuites(suiteOf(cliCase, { all_nodes: true }), CTX)
  if (!allNodes.some((p) => p.severity === 'error' && p.field.includes('mode'))) {
    return 'all_nodes did not veto cli mode'
  }
  return null
})

// --- Fact completion (delta 32) ---

// A namespace shaped like a real one: promised core in place, netlab's own
// keys under `_extras`.
const FACTS = {
  r1: {
    name: 'r1',
    device: 'vyos',
    loopback: { ipv4: '10.0.0.1/32' },
    ospf: { router_id: '10.0.0.1', area: '0.0.0.0' },
    _extras: { mtu: 1500 },
  },
  h1: { name: 'h1', device: 'linux' },
}
const ROOT = factRoot(FACTS, 'r1')

function offered(before) {
  const request = completionRequest(before)
  if (request === null) return null
  return factCompletions(request, ROOT).map((o) => o.label)
}

check('nothing is offered outside a template expression', () => {
  if (completionRequest('ping -c 3 ') !== null) return 'offered inside plain shell words'
  if (completionRequest('{{ node.ospf }} then ') !== null) return 'offered after the expression closed'
  return null
})

check('the roots are offered as soon as an expression opens', () => {
  const labels = offered('ping {{ ')
  if (labels === null) return 'nothing offered'
  if (!labels.includes('node') || !labels.includes('nodes')) return `got ${labels.join(',')}`
  return null
})

check('a path walks the namespace', () => {
  const top = offered('{{ node.')
  if (!top.includes('loopback') || !top.includes('ospf')) return `top: ${top.join(',')}`
  const ospf = offered('{{ node.ospf.')
  if (ospf.join(',') !== 'router_id,area') return `ospf: ${ospf.join(',')}`
  // `nodes` is keyed by node name.
  const byName = offered('{{ nodes.')
  if (byName.join(',') !== 'r1,h1') return `nodes: ${byName.join(',')}`
  if (!offered('{{ nodes.r1.').includes('loopback')) return 'nodes.<name> did not walk'
  return null
})

check('a partial word filters, and a miss offers nothing', () => {
  if (offered('{{ node.loop').join(',') !== 'loopback') return 'prefix did not filter'
  if (offered('{{ node.nope.').length !== 0) return 'a dead path offered something'
  // A scalar has no keys beneath it.
  if (offered('{{ node.ospf.router_id.').length !== 0) return 'a scalar offered keys'
  return null
})

check('the address filter is offered after a pipe', () => {
  const labels = offered('{{ node.loopback.ipv4 | ')
  if (!labels.includes('address')) return `got ${labels.join(',')}`
  return null
})

check('_extras is offered, and says what it costs', () => {
  const request = completionRequest('{{ node.')
  const extras = factCompletions(request, ROOT).find((o) => o.label === '_extras')
  if (extras === undefined) return 'not offered'
  if (!/no stability promise/.test(extras.detail)) return `detail was "${extras.detail}"`
  return null
})

check('containers apply with a trailing dot, scalars without', () => {
  const request = completionRequest('{{ node.')
  const options = factCompletions(request, ROOT)
  const loopback = options.find((o) => o.label === 'loopback')
  const device = options.find((o) => o.label === 'device')
  if (!loopback.container) return 'a nested object was not a container'
  if (device.container) return 'a scalar was marked a container'
  return null
})


// --- Reading a run (lib/test-results.ts) ---------------------------------
//
// The wire hands back one flat row per (test, node); everything here is the
// re-centring onto the TEST that the Tests tab reads.

function resultOf(test, node, status, extra = {}) {
  return {
    test,
    node,
    status,
    command: `echo ${node}`,
    output: '',
    detail: '',
    elapsed_ms: 10,
    ...extra,
  }
}

function reportOf(suite, results, at = '2026-08-11T10:00:00Z') {
  const counts = { pass: 0, fail: 0, skip: 0, error: 0 }
  for (const r of results) counts[r.status] = (counts[r.status] ?? 0) + 1
  return {
    suite,
    stage: 'runtime',
    passed: counts.pass,
    failed: counts.fail,
    skipped: counts.skip,
    errored: counts.error,
    ran_at: at,
    results,
  }
}

check('an unknown status reads as error, never as a pass', () => {
  if (readStatus('pass') !== 'pass') return 'pass did not survive'
  if (readStatus('weird') !== 'error') return `got ${readStatus('weird')}`
  return null
})

check('a roll-up takes the worst node, and error outranks fail', () => {
  if (rollUp([resultOf('t', 'r1', 'pass'), resultOf('t', 'r2', 'skip')]) !== 'skip') {
    return 'skip did not beat pass'
  }
  if (rollUp([resultOf('t', 'r1', 'pass'), resultOf('t', 'r2', 'fail')]) !== 'fail') {
    return 'fail did not beat pass'
  }
  if (rollUp([resultOf('t', 'r1', 'fail'), resultOf('t', 'r2', 'error')]) !== 'error') {
    return 'error did not beat fail'
  }
  return null
})

check('a test with no results rolls up to null, which is not a pass', () => {
  if (rollUp([]) !== null) return `got ${rollUp([])}`
  return null
})

check('results group by test and keep the server node order', () => {
  const report = reportOf('s', [
    resultOf('a', 'r2', 'pass'),
    resultOf('b', 'r1', 'fail'),
    resultOf('a', 'r1', 'pass'),
  ])
  const outcomes = outcomesByTest(report)
  if (outcomes.size !== 2) return `grouped into ${outcomes.size}`
  const a = outcomes.get('a')
  if (a.results.map((r) => r.node).join(',') !== 'r2,r1') {
    return `order was ${a.results.map((r) => r.node).join(',')}`
  }
  if (a.tally.pass !== 2 || a.tally.total !== 2) return 'tally was wrong'
  if (outcomes.get('b').status !== 'fail') return 'roll-up was wrong'
  return null
})

check('a suite that never ran groups into nothing', () => {
  if (outcomesByTest(undefined).size !== 0) return 'not empty'
  return null
})

check('results naming a test the suite dropped are reported as orphans', () => {
  const suite = { stage: 'runtime', description: '', tests: { kept: testOf(blankCase()) } }
  const report = reportOf('s', [resultOf('kept', 'r1', 'pass'), resultOf('gone', 'r1', 'pass')])
  const orphans = orphanedTests(suite, report)
  if (orphans.join(',') !== 'gone') return `got ${orphans.join(',')}`
  if (orphanedTests(suite, undefined).length !== 0) return 'a missing report invented orphans'
  return null
})

check('a report tally reshapes the server counts rather than recounting rows', () => {
  // The report's own counts are the authority — a second opinion computed from
  // `results` could disagree and there would be no way to tell which was right.
  const report = reportOf('s', [resultOf('t', 'r1', 'pass'), resultOf('t', 'r2', 'fail')])
  const counts = reportTally(report)
  if (counts.pass !== 1 || counts.fail !== 1) return `got ${JSON.stringify(counts)}`
  if (counts.total !== 2) return `total ${counts.total}`
  return null
})

check('a suite is failing on an ERROR too, not only a fail', () => {
  if (suiteStatus(undefined) !== 'not-run') return 'a missing report was not not-run'
  if (suiteStatus(reportOf('s', [resultOf('t', 'r1', 'pass')])) !== 'passing') return 'not passing'
  if (suiteStatus(reportOf('s', [resultOf('t', 'r1', 'error')])) !== 'failing') {
    return 'an errored suite read as passing'
  }
  return null
})

check('the lab summary counts every suite but only the runs that happened', () => {
  const suites = {
    a: { stage: 'runtime', description: '', tests: { t1: testOf(blankCase()), t2: testOf(blankCase()) } },
    b: { stage: 'runtime', description: '', tests: { t3: testOf(blankCase()) } },
  }
  const reports = {
    a: reportOf('a', [resultOf('t1', 'r1', 'pass'), resultOf('t2', 'r1', 'fail')], '2026-08-11T09:00:00Z'),
  }
  const summary = labValidation(suites, reports)
  if (summary.suitesTotal !== 2) return `suitesTotal ${summary.suitesTotal}`
  if (summary.suitesRun !== 1) return `suitesRun ${summary.suitesRun}`
  if (summary.suitesFailing !== 1) return `suitesFailing ${summary.suitesFailing}`
  if (summary.testsTotal !== 3) return `testsTotal ${summary.testsTotal}`
  if (summary.tally.total !== 2) return `tally.total ${summary.tally.total}`
  if (summary.lastRunAt !== '2026-08-11T09:00:00Z') return `lastRunAt ${summary.lastRunAt}`
  return null
})

check('lastRunAt is the NEWEST run, not the last suite in the map', () => {
  const suites = {
    a: { stage: 'runtime', description: '', tests: { t: testOf(blankCase()) } },
    b: { stage: 'runtime', description: '', tests: { t: testOf(blankCase()) } },
  }
  const summary = labValidation(suites, {
    a: reportOf('a', [resultOf('t', 'r1', 'pass')], '2026-08-11T12:00:00Z'),
    b: reportOf('b', [resultOf('t', 'r1', 'pass')], '2026-08-11T08:00:00Z'),
  })
  if (summary.lastRunAt !== '2026-08-11T12:00:00Z') return `got ${summary.lastRunAt}`
  return null
})

check('nothing run at all leaves lastRunAt null rather than a fake stamp', () => {
  const summary = labValidation(
    { a: { stage: 'runtime', description: '', tests: { t: testOf(blankCase()) } } },
    {},
  )
  if (summary.lastRunAt !== null) return `got ${summary.lastRunAt}`
  if (summary.tally.total !== 0) return 'counted results that do not exist'
  return null
})

check('the problems filter shows fails and errors, and hides a skip', () => {
  const outcome = (status) => ({ status, tally: { pass: 0, fail: 0, skip: 0, error: 0, total: 0 }, results: [] })
  if (!matchesFilter(outcome('fail'), 'problems')) return 'a fail was hidden'
  if (!matchesFilter(outcome('error'), 'problems')) return 'an error was hidden'
  if (matchesFilter(outcome('skip'), 'problems')) return 'a skip showed as a problem'
  if (matchesFilter(outcome('pass'), 'problems')) return 'a pass showed as a problem'
  return null
})

check('the not-run filter is about having no results, not about skipping', () => {
  const outcome = (status) => ({ status, tally: { pass: 0, fail: 0, skip: 0, error: 0, total: 0 }, results: [] })
  if (!matchesFilter(outcome(null), 'not-run')) return 'a test with no results was hidden'
  if (matchesFilter(outcome('skip'), 'not-run')) return 'a skip counted as not run'
  if (!matchesFilter(outcome('pass'), 'all')) return 'all hid something'
  return null
})

check('a tally line names only the buckets that happened', () => {
  const line = tallyLine({ pass: 6, fail: 0, skip: 0, error: 0, total: 6 })
  if (line !== '6 passed') return `got "${line}"`
  const mixed = tallyLine({ pass: 1, fail: 2, skip: 0, error: 3, total: 6 })
  if (mixed !== '1 passed · 2 failed · 3 errored') return `got "${mixed}"`
  if (tallyLine({ pass: 0, fail: 0, skip: 0, error: 0, total: 0 }) !== 'no results') {
    return 'an empty tally did not say so'
  }
  return null
})

check('elapsed time switches unit at a second and never invents one', () => {
  if (formatElapsed(120) !== '120ms') return `got ${formatElapsed(120)}`
  if (formatElapsed(2400) !== '2.4s') return `got ${formatElapsed(2400)}`
  if (formatElapsed(Number.NaN) !== '—') return 'NaN produced a number'
  return null
})

check('a unique name skips what is taken instead of overwriting it', () => {
  if (uniqueName(['a'], 'b') !== 'b') return 'a free name was changed'
  if (uniqueName(['check'], 'check') !== 'check2') return `got ${uniqueName(['check'], 'check')}`
  if (uniqueName(['check', 'check2'], 'check') !== 'check3') return 'the counter did not advance'
  return null
})

if (failures.length > 0) {
  console.error(`\n${failures.length} check(s) failed:\n`)
  for (const failure of failures) console.error(`  - ${failure}`)
  process.exit(1)
}
console.log(`test-suite-model: ${pass} checks passed`)
