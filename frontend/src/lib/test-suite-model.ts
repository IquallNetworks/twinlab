// The test-suite model: pure helpers the visual builder and its check harness
// share (delta 31).
//
// Deliberately pure — no React, no zod, no `@/` alias — so `pnpm
// check:test-suites` can bundle and exercise it under plain node, the same
// arrangement lib/build-doc.ts uses.
//
// Unlike a netlab definition, a suite's schema is CLOSED: Twinlab owns every
// field, so the builder can be total and this module never needs an extras
// passthrough. The one exception is `compare`, an arbitrary nested spec handed
// to napalm-validate — that stays raw, because it is another library's grammar.

import type { TestCase, TestExpectation, TestSuite, ValidationTest } from './schemas'

// --- Names ---------------------------------------------------------------

// The server's `_Name`: a path-safe charset, because a suite name is a URL
// segment. Narrower than netlab's node-id rule, and unrelated to it.
export const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/
export const NAME_MAX_LENGTH = 64

export function nameProblem(name: string): string | null {
  if (name === '') return 'Name is required'
  if (name.length > NAME_MAX_LENGTH) return `Name is longer than ${NAME_MAX_LENGTH} characters`
  if (!NAME_PATTERN.test(name)) {
    return 'Name must start with a letter or digit, then letters, digits, dot, dash or underscore'
  }
  return null
}

/** A name not already taken, by appending a counter — what a new or duplicated
 * test needs so a create never silently overwrites a sibling. */
export function uniqueName(taken: readonly string[], base: string): string {
  if (!taken.includes(base)) return base
  for (let n = 2; ; n += 1) {
    const candidate = `${base}${n}`
    if (!taken.includes(candidate)) return candidate
  }
}

// --- Expectations --------------------------------------------------------

export type MatcherKind = 'contains' | 'not_contains' | 'matches' | 'compare'
export const MATCHER_KINDS: readonly MatcherKind[] = [
  'contains',
  'not_contains',
  'matches',
  'compare',
]

/** Which matcher an expectation carries, or null when it carries none or
 * several — both of which the server rejects, so the UI needs to see them. */
export function matcherKind(expect: TestExpectation | undefined): MatcherKind | null {
  if (expect === undefined) return null
  const set = MATCHER_KINDS.filter((kind) => expect[kind] != null)
  return set.length === 1 ? (set[0] ?? null) : null
}

/** Switch an expectation to a different matcher. The three raw matchers are
 * all plain strings, so the text carries across a switch between them; going
 * to or from `compare` cannot carry anything, since one side is a spec. */
export function withMatcher(expect: TestExpectation | undefined, kind: MatcherKind): TestExpectation {
  const current = matcherKind(expect)
  const carried =
    current !== null && current !== 'compare' && kind !== 'compare'
      ? ((expect?.[current] as string | null | undefined) ?? '')
      : ''
  if (kind === 'compare') return { compare: {} }
  return { [kind]: carried } as TestExpectation
}

// --- Cases ---------------------------------------------------------------

/** A test's `run` is ONE case for every node, or a DEVICE-KEYED map (one suite
 * serving several NOS flavours). A TestCase always carries `command`, so its
 * presence discriminates — the same test the wire schema's union uses. */
export function isDeviceKeyed(
  run: TestCase | Record<string, TestCase>,
): run is Record<string, TestCase> {
  return !('command' in run)
}

export interface CaseEntry {
  /** null for the shared case — "every device", not a device named "". */
  device: string | null
  testCase: TestCase
}

export function caseEntries(run: TestCase | Record<string, TestCase>): CaseEntry[] {
  if (!isDeviceKeyed(run)) return [{ device: null, testCase: run }]
  return Object.entries(run).map(([device, testCase]) => ({ device, testCase }))
}

export function blankCase(): TestCase {
  return { command: '', expect: { contains: '' }, mode: 'shell', interactive: false }
}

/** A new test targets EVERY node (delta 32). That is the edit-proof default
 * and the one that stays correct as the lab grows — narrowing is a deliberate
 * act, where forgetting to widen is a silent one. */
export function blankTest(): ValidationTest {
  return { run: blankCase(), nodes: [], groups: [], all_nodes: true, wait: 0, description: '' }
}

export function blankSuite(): TestSuite {
  return { stage: 'runtime', description: '', tests: { check: blankTest() } }
}

/** The nodes a test runs on — the client-side mirror of the server's
 * `resolve_targets`, including its first-appearance order, so the builder can
 * show what a target actually selects before anything is saved. */
export function resolveTargets(
  test: ValidationTest,
  nodes: readonly string[],
  groups: ReadonlyMap<string, readonly string[]>,
): string[] {
  const seen = new Set<string>()
  if (test.all_nodes) for (const node of nodes) seen.add(node)
  for (const group of test.groups) for (const node of groups.get(group) ?? []) seen.add(node)
  for (const node of test.nodes) seen.add(node)
  return [...seen]
}

/** Convert between the shared and device-keyed forms without losing the case
 * the author already wrote: collapsing keeps the first case, expanding seeds
 * every named device with a copy of the shared one. */
export function toDeviceKeyed(
  run: TestCase | Record<string, TestCase>,
  devices: readonly string[],
): Record<string, TestCase> {
  if (isDeviceKeyed(run)) return run
  return Object.fromEntries(devices.map((device) => [device, { ...run }]))
}

export function toSharedCase(run: TestCase | Record<string, TestCase>): TestCase {
  if (!isDeviceKeyed(run)) return run
  return Object.values(run)[0] ?? blankCase()
}

// --- Validation ----------------------------------------------------------

export interface DeviceCapability {
  cliMode: boolean
  textfsm: boolean
}

export interface SuiteContext {
  /** The lab's node names. Empty on a bare record, where membership cannot be
   * checked and deliberately is not. */
  nodes: readonly string[]
  deviceByNode: ReadonlyMap<string, string>
  capabilities: ReadonlyMap<string, DeviceCapability>
  /** The definition's groups, resolved to node names (delta 32). */
  groups: ReadonlyMap<string, readonly string[]>
}

export interface SuiteProblem {
  suite: string
  test: string
  field: string
  message: string
  /** "error" is what the PUT itself rejects, so Save is blocked on it.
   * "warning" is what will fail at RUN time — worth saying now, but the
   * server would accept the save, and the builder does not get to be
   * stricter than the contract. */
  severity: 'error' | 'warning'
}

const WAIT_MAX_SECONDS = 600

function capabilityFor(
  ctx: SuiteContext,
  device: string | null,
  nodes: readonly string[],
): { device: string; capability: DeviceCapability }[] {
  // A device-keyed case names its own device; a shared one has to answer for
  // every node it targets, exactly as the server's own mode check does.
  const devices =
    device !== null
      ? [device]
      : nodes.map((node) => ctx.deviceByNode.get(node)).filter((d): d is string => d !== undefined)
  const seen = new Set<string>()
  const out: { device: string; capability: DeviceCapability }[] = []
  for (const name of devices) {
    if (seen.has(name)) continue
    seen.add(name)
    const capability = ctx.capabilities.get(name)
    if (capability !== undefined) out.push({ device: name, capability })
  }
  return out
}

function checkCase(
  suite: string,
  test: string,
  entry: CaseEntry,
  nodes: readonly string[],
  ctx: SuiteContext,
  push: (problem: SuiteProblem) => void,
): void {
  const where = entry.device === null ? 'run' : `run[${entry.device}]`
  const testCase = entry.testCase
  const error = (field: string, message: string): void =>
    push({ suite, test, field: `${where}.${field}`, message, severity: 'error' })
  const warning = (field: string, message: string): void =>
    push({ suite, test, field: `${where}.${field}`, message, severity: 'warning' })

  if (testCase.command.trim() === '') error('command', 'A command is required')

  const kind = matcherKind(testCase.expect)
  if (kind === null) {
    error('expect', 'Exactly one of contains, not_contains, matches or compare is required')
  }
  // compare asserts over PARSED data, and parsed data is only asserted with
  // compare — the server checks this both ways, so mirroring it needs both.
  const parse = testCase.parse ?? null
  if (kind === 'compare' && parse === null) {
    error('parse', 'compare asserts over parsed data, so the case must declare parse')
  }
  if (kind !== null && kind !== 'compare' && parse !== null) {
    error('expect', `parsed data is only asserted with compare, not ${kind}`)
  }
  if (kind === 'matches') {
    const pattern = testCase.expect.matches ?? ''
    try {
      // Syntax only: JS and Python regex semantics differ, so this catches a
      // broken pattern without claiming the two engines agree.
      void new RegExp(pattern)
    } catch (err) {
      error('expect.matches', err instanceof Error ? err.message : 'Not a valid regular expression')
    }
  }

  for (const { device, capability } of capabilityFor(ctx, entry.device, nodes)) {
    if (testCase.mode === 'cli' && !capability.cliMode) {
      // The PUT rejects this outright, so it is an error and not a warning.
      error(
        'mode',
        `${device} has no CLI of its own — its shell is the interface, so use shell mode`,
      )
    }
    if (parse === 'textfsm' && !capability.textfsm) {
      warning('parse', `${device} has no TextFSM template set, so this case will error at run time`)
    }
  }
}

/** Mirror of the server's own gates, so the builder can refuse before the PUT
 * does. Deliberately not stricter than the contract: anything the PUT would
 * accept comes back as a warning at most. */
export function validateSuites(
  suites: Record<string, TestSuite>,
  ctx: SuiteContext,
): SuiteProblem[] {
  const problems: SuiteProblem[] = []
  const push = (problem: SuiteProblem): void => {
    problems.push(problem)
  }

  for (const [suiteName, suite] of Object.entries(suites)) {
    const suiteNameProblem = nameProblem(suiteName)
    if (suiteNameProblem !== null) {
      push({ suite: suiteName, test: '', field: 'name', message: suiteNameProblem, severity: 'error' })
    }
    if (Object.keys(suite.tests).length === 0) {
      push({
        suite: suiteName,
        test: '',
        field: 'tests',
        message: 'A suite needs at least one test',
        severity: 'error',
      })
    }

    for (const [testName, test] of Object.entries(suite.tests)) {
      const testNameProblem = nameProblem(testName)
      if (testNameProblem !== null) {
        push({
          suite: suiteName,
          test: testName,
          field: 'name',
          message: testNameProblem,
          severity: 'error',
        })
      }
      if (!test.all_nodes && test.groups.length === 0 && test.nodes.length === 0) {
        push({
          suite: suiteName,
          test: testName,
          field: 'nodes',
          message: 'A test must target something: all nodes, a group, or named nodes',
          severity: 'error',
        })
      }
      // Only when the lab HAS nodes: a suite authored before the definition
      // is legitimate, and the server accepts it too.
      if (ctx.nodes.length > 0) {
        for (const node of test.nodes) {
          if (!ctx.nodes.includes(node)) {
            push({
              suite: suiteName,
              test: testName,
              field: 'nodes',
              message: `'${node}' is not a node in this lab`,
              severity: 'warning',
            })
          }
        }
        for (const group of test.groups) {
          if (!ctx.groups.has(group)) {
            push({
              suite: suiteName,
              test: testName,
              field: 'groups',
              message: `'${group}' is not a group in this lab`,
              severity: 'warning',
            })
          }
        }
        // A target that resolves to nothing runs nothing — the server accepts
        // it (the group may come back), but silence is the failure mode this
        // whole delta exists to prevent, so say it.
        if (resolveTargets(test, ctx.nodes, ctx.groups).length === 0) {
          push({
            suite: suiteName,
            test: testName,
            field: 'nodes',
            message: 'This target selects no nodes, so the test would not run',
            severity: 'warning',
          })
        }
      }
      if (test.wait < 0 || test.wait > WAIT_MAX_SECONDS) {
        push({
          suite: suiteName,
          test: testName,
          field: 'wait',
          message: `Wait must be between 0 and ${WAIT_MAX_SECONDS} seconds`,
          severity: 'error',
        })
      }
      if (isDeviceKeyed(test.run) && Object.keys(test.run).length === 0) {
        push({
          suite: suiteName,
          test: testName,
          field: 'run',
          message: 'A device-keyed run needs at least one case',
          severity: 'error',
        })
      }
      const targets = resolveTargets(test, ctx.nodes, ctx.groups)
      for (const entry of caseEntries(test.run)) {
        checkCase(suiteName, testName, entry, targets, ctx, push)
      }
    }
  }
  return problems
}

export function hasBlockingProblem(problems: readonly SuiteProblem[]): boolean {
  return problems.some((problem) => problem.severity === 'error')
}
