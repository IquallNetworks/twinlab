import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Braces, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { FactsViewer } from '@/components/lab/tests/facts-viewer'
import { SuiteCard } from '@/components/lab/tests/suite-card'
import { SuiteSettingsDialog } from '@/components/lab/tests/suite-settings-dialog'
import { SuitesJsonDialog } from '@/components/lab/tests/suites-json-dialog'
import { TestEditDialog } from '@/components/lab/tests/test-edit-dialog'
import { useSaveSuites, type Suites } from '@/components/lab/tests/use-save-suites'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api, waitJob } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { formatAgo, formatDateTime } from '@/lib/format'
import { PERM_LAB_EDIT, PERM_LAB_VALIDATE } from '@/lib/lab-permissions'
import { labQueryOptions, labsQueryOptions, testSuitesQueryOptions } from '@/lib/queries'
import {
  suiteReportSchema,
  type SuiteReport,
  type TestSuite,
  type ValidationTest,
} from '@/lib/schemas'
import { labValidation, reportTally, tallyLine, type ResultFilter } from '@/lib/test-results'
import { blankTest, uniqueName, validateSuites } from '@/lib/test-suite-model'
import { useSuiteAuthoring } from '@/lib/use-suite-authoring'

/** What the whole lab's validation says, in one strip. The counts are over
 * RESULTS, matching what the suite reports themselves count — a summary that
 * disagreed with the rows under it would be worse than none.
 *
 * The counts are also the FILTER: "1 failed" is both the answer to "is
 * anything wrong" and the way to go look, which is the next thing anyone does
 * with it. */
function CountChip({
  label,
  tone,
  active,
  onClick,
}: {
  label: string
  tone: 'quiet' | 'loud'
  active: boolean
  onClick?: () => void
}) {
  const text = tone === 'loud' ? 'text-destructive font-medium' : 'text-muted-foreground'
  if (onClick === undefined) return <span className={`text-xs ${text}`}>{label}</span>
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-1.5 py-0.5 text-xs underline-offset-2 hover:underline ${text} ${
        active ? 'bg-muted' : ''
      }`}
    >
      {label}
    </button>
  )
}

function ValidationSummary({
  suites,
  reports,
  configTimeFailed,
  filter,
  onFilter,
}: {
  suites: Suites
  reports: Record<string, SuiteReport>
  configTimeFailed: boolean
  filter: ResultFilter
  onFilter: (next: ResultFilter) => void
}) {
  const summary = labValidation(suites, reports)
  const never = summary.suitesTotal - summary.suitesRun
  const problems = summary.tally.fail + summary.tally.error

  return (
    <Card className="py-4">
      <CardContent className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="text-sm">
          <span className="font-medium">
            {summary.suitesTotal} suite{summary.suitesTotal === 1 ? '' : 's'}
          </span>{' '}
          · {summary.testsTotal} test{summary.testsTotal === 1 ? '' : 's'}
        </p>
        <div className="flex flex-wrap items-center gap-1">
          {summary.tally.pass > 0 && (
            <CountChip label={`${summary.tally.pass} passed`} tone="quiet" active={false} />
          )}
          {problems > 0 && (
            <CountChip
              label={tallyLine({ ...summary.tally, pass: 0, skip: 0, total: problems })}
              tone="loud"
              active={filter === 'problems'}
              onClick={() => onFilter(filter === 'problems' ? 'all' : 'problems')}
            />
          )}
          {summary.tally.skip > 0 && (
            <CountChip label={`${summary.tally.skip} skipped`} tone="quiet" active={false} />
          )}
          {never > 0 && (
            <CountChip
              label={`${never} suite${never === 1 ? '' : 's'} never run`}
              tone="quiet"
              active={filter === 'not-run'}
              onClick={() => onFilter(filter === 'not-run' ? 'all' : 'not-run')}
            />
          )}
        </div>
        <p className="text-muted-foreground ml-auto text-xs">
          {summary.lastRunAt === null ? (
            'Nothing has run yet.'
          ) : (
            <span title={formatDateTime(summary.lastRunAt)}>
              last run {formatAgo(summary.lastRunAt)}
            </span>
          )}
        </p>
        {summary.suitesFailing > 0 && (
          <p className="text-destructive w-full text-sm font-medium">
            {summary.suitesFailing} suite{summary.suitesFailing === 1 ? '' : 's'} failing
          </p>
        )}
        {configTimeFailed && (
          <p className="text-destructive w-full text-sm">
            Config-time validation failed on the last configure — the lab is deployed but did not
            pass its convergence checks.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

type Confirm = { kind: 'suite'; suite: string } | { kind: 'test'; suite: string; test: string }

/** The Tests tab: a lab's validation, as a page rather than a card.
 *
 * Suites used to be rows on the Operations tab that expanded into one flat
 * (test, node) table, which is the shape the wire uses and the wrong shape to
 * read — a test that ran on eight nodes arrived as eight unrelated rows, and
 * the test itself (what it targets, what it runs) was only visible inside a
 * JSON editor. Here the TEST is the unit: it gets a card, its results collapse
 * onto it as per-node pills, and editing one opens a dialog about that test
 * alone. */
export function TestsTab({ name }: { name: string }) {
  const queryClient = useQueryClient()
  const { data: lab } = useQuery(labQueryOptions(name))
  const { data, isPending, isError, error } = useQuery(testSuitesQueryOptions(name))
  const authoring = useSuiteAuthoring(name)

  const [filter, setFilter] = useState<ResultFilter>('all')
  // A create and an edit are the same dialog: `initial*` carry the suite and
  // test that do not exist yet, so nothing incomplete is ever PUT.
  const [editing, setEditing] = useState<{
    suite: string
    test: string
    initialSuite?: TestSuite
    initialTest?: ValidationTest
  } | null>(null)
  const [settings, setSettings] = useState<{ suite: string | null } | null>(null)
  const [jsonOpen, setJsonOpen] = useState(false)
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const [running, setRunning] = useState<string | null>(null)

  const suites: Suites = useMemo(() => data?.test_suites ?? {}, [data])
  const problems = useMemo(
    () => validateSuites(suites, authoring.context),
    [suites, authoring.context],
  )
  const save = useSaveSuites(name)

  // A run is an async job; the terminal job's result is the SuiteReport. Run
  // all is the same verb in a loop — the per-lab job mutex makes concurrency
  // impossible anyway, and each suite's results land as it finishes.
  const run = useMutation({
    mutationFn: async (names: readonly string[]) => {
      const reports: SuiteReport[] = []
      for (const suite of names) {
        setRunning(suite)
        const job = await waitJob(name, await api.runTestSuite(name, suite))
        reports.push(suiteReportSchema.parse(job.result))
        await queryClient.invalidateQueries({
          queryKey: testSuitesQueryOptions(name).queryKey,
        })
      }
      return reports
    },
    onSuccess: async (reports) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: labQueryOptions(name).queryKey }),
        queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey }),
      ])
      const failed = reports.filter((report) => report.failed > 0 || report.errored > 0)
      const only = reports.length === 1 ? reports[0] : undefined
      const message =
        only !== undefined
          ? `${only.suite}: ${tallyLine(reportTally(only))}`
          : `${reports.length} suites run, ${failed.length} failing`
      if (failed.length === 0) toast.success(message)
      else toast.error(message)
    },
    onError: (err) => toastError(err, 'Run failed'),
    onSettled: () => {
      setRunning(null)
      void queryClient.invalidateQueries({ queryKey: ['jobs', name] })
    },
  })

  if (!lab) return null
  const canEdit = lab.permissions.includes(PERM_LAB_EDIT)
  const canValidate = lab.permissions.includes(PERM_LAB_VALIDATE)
  const deployed = lab.status === 'deployed'
  const suiteNames = Object.keys(suites)

  function addTest(suiteName: string): void {
    const suite = suites[suiteName]
    if (suite === undefined) return
    setEditing({
      suite: suiteName,
      test: uniqueName(Object.keys(suite.tests), 'check'),
      initialTest: blankTest(),
    })
  }

  function duplicateTest(suiteName: string, testName: string): void {
    const suite = suites[suiteName]
    const test = suite?.tests[testName]
    if (suite === undefined || test === undefined) return
    const copy = uniqueName(Object.keys(suite.tests), `${testName}-copy`)
    save.mutate({
      ...suites,
      [suiteName]: { ...suite, tests: { ...suite.tests, [copy]: structuredClone(test) } },
    })
  }

  function applyConfirm(target: Confirm): void {
    if (target.kind === 'suite') {
      const { [target.suite]: _removed, ...rest } = suites
      save.mutate(rest)
      return
    }
    const suite = suites[target.suite]
    if (suite === undefined) return
    const { [target.test]: _removed, ...tests } = suite.tests
    save.mutate({ ...suites, [target.suite]: { ...suite, tests } })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Tabs value={filter} onValueChange={(value) => setFilter(value as ResultFilter)}>
          <TabsList>
            <TabsTrigger value="all">All tests</TabsTrigger>
            <TabsTrigger value="problems">Problems</TabsTrigger>
            <TabsTrigger value="not-run">Not run</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex flex-wrap items-center gap-1">
          <FactsViewer name={name} />
          {canValidate && suiteNames.length > 1 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => run.mutate(suiteNames)}
              disabled={!deployed || run.isPending}
              title={deployed ? undefined : 'Run is available while the lab is running'}
            >
              {/* Only when THIS button started the batch. A single suite's run
                  also holds the mutex, so it disables this one — but saying
                  "Running…" here would point at the wrong thing. */}
              {run.isPending && (run.variables?.length ?? 0) > 1 ? 'Running…' : 'Run all'}
            </Button>
          )}
          {canEdit && (
            <>
              <Button variant="outline" size="sm" onClick={() => setJsonOpen(true)}>
                <Braces className="size-3.5" />
                JSON
              </Button>
              <Button variant="outline" size="sm" onClick={() => setSettings({ suite: null })}>
                <Plus className="size-3.5" />
                New suite
              </Button>
            </>
          )}
        </div>
      </div>

      {isPending ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : isError ? (
        <p className="text-destructive text-sm">
          {error instanceof Error ? error.message : 'Failed to load test suites'}
        </p>
      ) : (
        <>
          <ValidationSummary
            suites={suites}
            reports={data.last_validation}
            configTimeFailed={data.config_time_status === 'failed'}
            filter={filter}
            onFilter={setFilter}
          />

          {suiteNames.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
                <p className="text-muted-foreground text-sm">
                  No test suites yet. A suite is a set of declarative checks — a command per node
                  and what its output has to say — run on demand, or as a gate on every configure.
                </p>
                {canEdit && (
                  <Button variant="outline" size="sm" onClick={() => setSettings({ suite: null })}>
                    Create the first suite
                  </Button>
                )}
              </CardContent>
            </Card>
          ) : (
            // config-time suites first: they gate a configure and are the
            // headline check.
            [...Object.entries(suites)]
              .sort(
                ([, a], [, b]) =>
                  (a.stage === 'config-time' ? 0 : 1) - (b.stage === 'config-time' ? 0 : 1),
              )
              .map(([suiteName, suite]) => (
                <SuiteCard
                  key={suiteName}
                  suiteName={suiteName}
                  suite={suite}
                  report={data.last_validation[suiteName]}
                  filter={filter}
                  problems={problems}
                  groups={authoring.groups}
                  nodes={authoring.nodes}
                  enabled={deployed}
                  canEdit={canEdit}
                  canValidate={canValidate}
                  running={running === suiteName}
                  onRun={(target) => run.mutate([target])}
                  onSettings={(target) => setSettings({ suite: target })}
                  onAddTest={addTest}
                  onEditTest={(target, test) => setEditing({ suite: target, test })}
                  onDuplicateTest={duplicateTest}
                  onDeleteTest={(target, test) =>
                    setConfirm({ kind: 'test', suite: target, test })
                  }
                  onDeleteSuite={(target) => setConfirm({ kind: 'suite', suite: target })}
                />
              ))
          )}
        </>
      )}

      {editing !== null && data !== undefined && (
        <TestEditDialog
          labName={name}
          suiteName={editing.suite}
          testName={editing.test}
          suites={suites}
          initialSuite={editing.initialSuite}
          initialTest={editing.initialTest}
          authoring={authoring}
          onClose={() => setEditing(null)}
        />
      )}
      {settings !== null && data !== undefined && (
        <SuiteSettingsDialog
          labName={name}
          suites={suites}
          suiteName={settings.suite}
          onCreate={(suiteName, suite) => {
            setSettings(null)
            setEditing({
              suite: suiteName,
              test: 'check',
              initialSuite: suite,
              initialTest: blankTest(),
            })
          }}
          onClose={() => setSettings(null)}
        />
      )}
      {jsonOpen && data !== undefined && (
        <SuitesJsonDialog labName={name} suites={suites} onClose={() => setJsonOpen(false)} />
      )}

      <AlertDialog open={confirm !== null} onOpenChange={(next) => !next && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirm?.kind === 'suite'
                ? `Delete suite ${confirm.suite}?`
                : `Delete test ${confirm?.test}?`}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirm?.kind === 'suite'
                ? 'Every test in it goes too. Authored suites are not versioned, so this cannot ' +
                  'be undone.'
                : 'Authored tests are not versioned, so this cannot be undone.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (confirm !== null) applyConfirm(confirm)
                setConfirm(null)
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
