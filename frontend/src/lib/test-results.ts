// Reading a validation run, as data. The wire gives one flat `results` array
// per suite — one row per (test, node) pair — which is the right shape to
// store and the wrong shape to read: a test that ran on eight nodes arrives as
// eight unrelated rows. Everything here re-centres that on the TEST, which is
// the thing an author writes and an operator asks about.
//
// Pure and dependency-free on purpose, so `pnpm check:test-suites` can drive
// it — the frontend has no test runner.

import type { SuiteReport, TestResult, TestSuite } from '@/lib/schemas'

/** The server's own vocabulary. `TestResult.status` stays a plain string on
 * the wire (an unknown value must remain displayable), so this is a reading
 * of it, not a parse. */
export type ResultStatus = 'pass' | 'fail' | 'skip' | 'error'

export const RESULT_STATUSES: readonly ResultStatus[] = ['pass', 'fail', 'skip', 'error']

/** Roll-up severity, worst-wins. `error` outranks `fail` deliberately: a fail
 * is an assertion that was made and came back false, while an error is one
 * that could not be made at all — the state you can conclude least from, and
 * the one most likely to mean the test itself is broken. The per-node pills
 * show the full picture regardless; this only decides the headline. */
const SEVERITY: Record<ResultStatus, number> = { pass: 0, skip: 1, fail: 2, error: 3 }

export function readStatus(raw: string): ResultStatus {
  // An unrecognised status is not a pass, and pretending otherwise would hide
  // it behind a green badge — so it ranks with the states we cannot read.
  return (RESULT_STATUSES as readonly string[]).includes(raw) ? (raw as ResultStatus) : 'error'
}

export interface Tally {
  pass: number
  fail: number
  skip: number
  error: number
  total: number
}

export function emptyTally(): Tally {
  return { pass: 0, fail: 0, skip: 0, error: 0, total: 0 }
}

export function tally(results: readonly TestResult[]): Tally {
  const out = emptyTally()
  for (const result of results) {
    out[readStatus(result.status)] += 1
    out.total += 1
  }
  return out
}

/** One test's last run, across every node it ran on. */
export interface TestOutcome {
  /** null when the last run holds nothing for this test — it was added after
   * the run, or the suite has never run at all. Not the same as a skip, which
   * is a node the test deliberately did not apply to. */
  status: ResultStatus | null
  tally: Tally
  results: readonly TestResult[]
}

export const NOT_RUN: TestOutcome = { status: null, tally: emptyTally(), results: [] }

export function rollUp(results: readonly TestResult[]): ResultStatus | null {
  let worst: ResultStatus | null = null
  for (const result of results) {
    const status = readStatus(result.status)
    if (worst === null || SEVERITY[status] > SEVERITY[worst]) worst = status
  }
  return worst
}

/** The suite's flat result list, re-centred on the test. Node order within a
 * test is preserved — it is the server's target resolution order, which is
 * itself meaningful (delta 32 pins it as first-appearance). */
export function outcomesByTest(report: SuiteReport | undefined): Map<string, TestOutcome> {
  const grouped = new Map<string, TestResult[]>()
  for (const result of report?.results ?? []) {
    const bucket = grouped.get(result.test)
    if (bucket === undefined) grouped.set(result.test, [result])
    else bucket.push(result)
  }
  return new Map(
    [...grouped].map(([test, results]) => [
      test,
      { status: rollUp(results), tally: tally(results), results },
    ]),
  )
}

/** Results naming a test the suite no longer defines — what a rename or a
 * delete leaves behind. Worth surfacing rather than dropping silently: it is
 * the difference between "this test passed" and "a test with that name passed,
 * once". */
export function orphanedTests(suite: TestSuite, report: SuiteReport | undefined): string[] {
  const defined = new Set(Object.keys(suite.tests))
  const seen = new Set<string>()
  for (const result of report?.results ?? []) {
    if (!defined.has(result.test)) seen.add(result.test)
  }
  return [...seen]
}

/** A suite report's own counts, as a Tally. The server already counted them,
 * so this reshapes rather than recounts — recounting `report.results` would be
 * a second opinion nobody asked for. */
export function reportTally(report: SuiteReport): Tally {
  return {
    pass: report.passed,
    fail: report.failed,
    skip: report.skipped,
    error: report.errored,
    total: report.passed + report.failed + report.skipped + report.errored,
  }
}

export type SuiteStatus = 'passing' | 'failing' | 'not-run'

export function suiteStatus(report: SuiteReport | undefined): SuiteStatus {
  if (report === undefined) return 'not-run'
  return report.failed > 0 || report.errored > 0 ? 'failing' : 'passing'
}

/** The whole lab's validation state in one line. Counts are over RESULTS (a
 * test on eight nodes is eight of them), because that is what the suite
 * reports count and a summary that disagreed with the rows below it would be
 * worse than no summary. */
export interface LabValidation {
  tally: Tally
  suitesTotal: number
  suitesRun: number
  suitesFailing: number
  testsTotal: number
  /** Newest `ran_at` across the suites that have run, or null. */
  lastRunAt: string | null
}

export function labValidation(
  suites: Record<string, TestSuite>,
  reports: Record<string, SuiteReport>,
): LabValidation {
  const out: LabValidation = {
    tally: emptyTally(),
    suitesTotal: 0,
    suitesRun: 0,
    suitesFailing: 0,
    testsTotal: 0,
    lastRunAt: null,
  }
  for (const [name, suite] of Object.entries(suites)) {
    out.suitesTotal += 1
    out.testsTotal += Object.keys(suite.tests).length
    const report = reports[name]
    if (report === undefined) continue
    out.suitesRun += 1
    if (suiteStatus(report) === 'failing') out.suitesFailing += 1
    const counts = reportTally(report)
    out.tally.pass += counts.pass
    out.tally.fail += counts.fail
    out.tally.skip += counts.skip
    out.tally.error += counts.error
    out.tally.total += counts.total
    // Lexicographic max is chronological max: these are ISO-8601 UTC stamps.
    if (out.lastRunAt === null || report.ran_at > out.lastRunAt) out.lastRunAt = report.ran_at
  }
  return out
}

/** What the tab is showing. `problems` is the one an operator lives in after
 * a run; `not-run` answers "what did I add since?". */
export type ResultFilter = 'all' | 'problems' | 'not-run'

export function matchesFilter(outcome: TestOutcome, filter: ResultFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'not-run') return outcome.status === null
  return outcome.status === 'fail' || outcome.status === 'error'
}

/** A one-line reading of a tally, omitting the zero buckets — "6 passed" beats
 * "6 passed · 0 failed · 0 skipped · 0 errored" for the case that is fine. */
export function tallyLine(counts: Tally): string {
  if (counts.total === 0) return 'no results'
  const parts: string[] = []
  if (counts.pass > 0) parts.push(`${counts.pass} passed`)
  if (counts.fail > 0) parts.push(`${counts.fail} failed`)
  if (counts.skip > 0) parts.push(`${counts.skip} skipped`)
  if (counts.error > 0) parts.push(`${counts.error} errored`)
  return parts.join(' · ')
}

/** Elapsed time as a run reports it. Sub-second work is the common case and
 * milliseconds are the honest unit there; seconds take over once the number
 * stops being readable. */
export function formatElapsed(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}
