import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { CodeEditor } from '@/components/code-editor'
import { api, waitJob } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { formatDateTime, testStatusBadgeVariant } from '@/lib/format'
import {
  labFactsQueryOptions,
  labQueryOptions,
  labsQueryOptions,
  testSuitesQueryOptions,
} from '@/lib/queries'
import { suiteReportSchema, type SuiteReport, type TestResult, type TestSuite } from '@/lib/schemas'

function summaryLine(report: SuiteReport): string {
  const parts = [`${report.passed} passed`, `${report.failed} failed`]
  if (report.skipped > 0) parts.push(`${report.skipped} skipped`)
  if (report.errored > 0) parts.push(`${report.errored} errored`)
  return `${parts.join(' · ')} · ${formatDateTime(report.ran_at)}`
}

/** One result's detail cell: the human line, the RENDERED command (what
 * actually ran — the debugging artifact for templated tests), and the compare
 * diff when one decided the outcome. */
function ResultDetail({ result }: { result: TestResult }) {
  return (
    <div className="flex flex-col gap-1">
      <span>{result.detail}</span>
      {result.command !== '' && (
        <span className="text-muted-foreground/70 font-mono text-[11px]">{result.command}</span>
      )}
      {result.diff != null && (
        <details>
          <summary className="cursor-pointer select-none text-[11px]">compare diff</summary>
          <pre className="bg-muted/50 mt-1 max-h-48 overflow-auto rounded p-2 text-[11px]">
            {JSON.stringify(result.diff, null, 1)}
          </pre>
        </details>
      )}
    </div>
  )
}

function ResultsTable({ report }: { report: SuiteReport }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Test</TableHead>
          <TableHead>Node</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Detail</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {report.results.map((r) => (
          <TableRow key={`${r.test}:${r.node}`}>
            <TableCell className="font-medium">{r.test}</TableCell>
            <TableCell className="font-mono text-xs">{r.node}</TableCell>
            <TableCell>
              <Badge variant={testStatusBadgeVariant(r.status)}>{r.status}</Badge>
            </TableCell>
            <TableCell className="text-muted-foreground text-xs">
              <ResultDetail result={r} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

/** Read-only viewer for the lab's fact namespace — what suite templates like
 * `{{ nodes.pe1.loopback.ipv4 | address }}` resolve against. Loaded lazily on
 * open (a bare record has no facts; the 409 renders as the error line).
 *
 * The payload is partitioned server-side (contract delta 26), so the two
 * stability tiers are visible in the JSON itself: anything under an `_extras`
 * key is netlab-shaped and unpromised. The copy below says so, because the
 * structural signal alone doesn't explain the consequence. */
function FactsViewer({ name }: { name: string }) {
  const [open, setOpen] = useState(false)
  const facts = useQuery({ ...labFactsQueryOptions(name), enabled: open })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm">
          Facts
        </Button>
      </DialogTrigger>
      <DialogContent className="flex flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Node facts</DialogTitle>
          <DialogDescription>
            The per-node namespace test templates render against — reference it as{' '}
            <span className="font-mono">{'{{ node.… }}'}</span> (the executing node) or{' '}
            <span className="font-mono">{'{{ nodes.<name>.… }}'}</span>, with the{' '}
            <span className="font-mono">| address</span> filter stripping a CIDR&apos;s prefix
            length. Derived from the definition.
          </DialogDescription>
        </DialogHeader>
        <p className="text-muted-foreground text-xs">
          Two tiers: everything <strong className="text-foreground">outside</strong>{' '}
          <span className="font-mono">_extras</span> is stable — it keeps its shape across netlab
          upgrades. Keys <strong className="text-foreground">inside</strong> an{' '}
          <span className="font-mono">_extras</span> object are netlab&apos;s own, carry{' '}
          <strong className="text-foreground">no promises</strong>, and may change or disappear
          when netlab does. A template may read them; it just isn&apos;t guaranteed to keep
          working.
        </p>
        {facts.isPending && open ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : facts.isError ? (
          <p className="text-destructive text-sm">
            {facts.error instanceof Error ? facts.error.message : 'Failed to load facts'}
          </p>
        ) : facts.data ? (
          <CodeEditor
            value={JSON.stringify(facts.data.nodes, null, 2)}
            language="json"
            readOnly
            className="max-h-[60vh] min-h-48 flex-1"
          />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

/** One suite: its stage/description, the last run's tally, a Run button, and an
 * expandable per-test result table. */
function SuiteRow({
  suiteName,
  suite,
  report,
  enabled,
  canValidate,
  running,
  onRun,
}: {
  suiteName: string
  suite: TestSuite
  report: SuiteReport | undefined
  enabled: boolean
  canValidate: boolean
  running: boolean
  onRun: (suite: string) => void
}) {
  const [open, setOpen] = useState(false)
  const failed = report !== undefined && (report.failed > 0 || report.errored > 0)

  return (
    <div className="rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => setOpen((v) => !v)}
            aria-label={open ? 'Collapse' : 'Expand'}
            disabled={report === undefined}
          >
            {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </button>
          <span className="font-medium">{suiteName}</span>
          <Badge variant={suite.stage === 'config-time' ? 'default' : 'secondary'}>
            {suite.stage}
          </Badge>
          {report !== undefined && (
            <Badge variant={failed ? 'destructive' : 'default'}>
              {failed ? 'failing' : 'passing'}
            </Badge>
          )}
        </div>
        {canValidate && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => onRun(suiteName)}
            disabled={!enabled || running}
            title={enabled ? undefined : 'Run is available while the lab is running'}
          >
            {running ? 'Running…' : 'Run'}
          </Button>
        )}
      </div>
      {suite.description !== '' && (
        <p className="text-muted-foreground mt-2 text-sm">{suite.description}</p>
      )}
      <p className="text-muted-foreground mt-1 text-xs">
        {report === undefined ? 'Not run yet.' : summaryLine(report)}
      </p>
      {open && report !== undefined && (
        <div className="mt-3">
          <ResultsTable report={report} />
        </div>
      )}
    </div>
  )
}

/** Author the whole suite set as JSON. Parsed here for syntax; the backend
 * validates the schema and surfaces any error. */
function SuitesEditor({ name, suitesJson }: { name: string; suitesJson: string }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState(suitesJson)

  const save = useMutation({
    mutationFn: (parsed: unknown) => api.putTestSuites(name, parsed),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: testSuitesQueryOptions(name).queryKey })
      toast.success('Saved test suites')
      setOpen(false)
    },
    onError: (err) => toastError(err, 'Failed to save suites'),
  })

  function onSave() {
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch (e) {
      toast.error(e instanceof Error ? `Invalid JSON: ${e.message}` : 'Invalid JSON')
      return
    }
    save.mutate(parsed)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) setText(suitesJson) // reset to the current suites on open
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Edit suites
        </Button>
      </DialogTrigger>
      <DialogContent className="flex flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit test suites</DialogTitle>
          <DialogDescription>
            A JSON map of suite name → {'{ stage, description, tests }'}. A test&apos;s{' '}
            <span className="font-mono">run</span> is one case{' '}
            <span className="font-mono">{'{ command, expect, parse?, interactive? }'}</span> or a
            device-keyed map of cases. Commands and expectations may template lab facts (
            <span className="font-mono">{'{{ nodes.pe1.loopback.ipv4 | address }}'}</span>) — see
            Facts for the namespace, and note that a path through{' '}
            <span className="font-mono">_extras</span> carries no stability promise.{' '}
            <span className="font-mono">expect</span> is one of contains / not_contains / matches /
            compare (compare pairs with <span className="font-mono">parse</span>).
          </DialogDescription>
        </DialogHeader>
        <CodeEditor
          value={text}
          onChange={setText}
          language="json"
          lint
          className="max-h-[60vh] min-h-48 flex-1"
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={onSave} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Test suites: declarative assertions run against the live lab. Config-time
 * suites also gate a configure; runtime suites run on demand. Everyone with
 * lab:read sees suites and their last run; lab:validate runs them; lab:create
 * authors them. */
export function TestSuites({
  name,
  enabled,
  canValidate,
  canEdit,
}: {
  name: string
  enabled: boolean
  canValidate: boolean
  canEdit: boolean
}) {
  const queryClient = useQueryClient()
  const [running, setRunning] = useState<string | null>(null)
  const { data, isPending, isError, error } = useQuery(testSuitesQueryOptions(name))

  // A run is an async job; the terminal job's result is the SuiteReport.
  const run = useMutation({
    mutationFn: async (suite: string) => waitJob(name, await api.runTestSuite(name, suite)),
    onSuccess: async (job) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: testSuitesQueryOptions(name).queryKey }),
        queryClient.invalidateQueries({ queryKey: labQueryOptions(name).queryKey }),
        queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey }),
      ])
      const report = suiteReportSchema.parse(job.result)
      const ok = report.failed === 0 && report.errored === 0
      const message = `${report.suite}: ${summaryLine(report)}`
      if (ok) toast.success(message)
      else toast.error(message)
    },
    onError: (err) => toastError(err, 'Run failed'),
    onSettled: () => {
      setRunning(null)
      void queryClient.invalidateQueries({ queryKey: ['jobs', name] })
    },
  })

  function onRun(suite: string) {
    setRunning(suite)
    run.mutate(suite)
  }

  const suites = data ? Object.entries(data.test_suites) : []
  // config-time suites first — they gate a configure and are the headline check.
  const ordered = [...suites].sort(([, a], [, b]) => {
    const rank = (s: TestSuite) => (s.stage === 'config-time' ? 0 : 1)
    return rank(a) - rank(b)
  })
  const suitesJson = data ? JSON.stringify(data.test_suites, null, 2) : '{}'

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">Test suites</CardTitle>
        <div className="flex items-center gap-1">
          <FactsViewer name={name} />
          {canEdit && data && <SuitesEditor name={name} suitesJson={suitesJson} />}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {isPending ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : isError ? (
          <p className="text-destructive text-sm">
            {error instanceof Error ? error.message : 'Failed to load test suites'}
          </p>
        ) : (
          <>
            {data.config_time_status === 'failed' && (
              <p className="text-destructive text-sm font-medium">
                Config-time validation failed on the last configure — the lab is deployed but did not
                pass its convergence checks.
              </p>
            )}
            {ordered.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                No test suites defined{canEdit ? ' — add some with “Edit suites”.' : '.'}
              </p>
            ) : (
              ordered.map(([suiteName, suite]) => (
                <SuiteRow
                  key={suiteName}
                  suiteName={suiteName}
                  suite={suite}
                  report={data.last_validation[suiteName]}
                  enabled={enabled}
                  canValidate={canValidate}
                  running={running === suiteName}
                  onRun={onRun}
                />
              ))
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
