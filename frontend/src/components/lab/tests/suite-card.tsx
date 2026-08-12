import { MoreHorizontal, Plus } from 'lucide-react'
import { useState } from 'react'

import {
  StageBadge,
  SuiteStatusBadge,
} from '@/components/lab/tests/status-badge'
import { TestCard } from '@/components/lab/tests/test-card'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { formatAgo, formatDateTime } from '@/lib/format'
import type { SuiteReport, TestSuite } from '@/lib/schemas'
import {
  NOT_RUN,
  matchesFilter,
  orphanedTests,
  outcomesByTest,
  reportTally,
  suiteStatus,
  tallyLine,
  type ResultFilter,
} from '@/lib/test-results'
import type { SuiteProblem } from '@/lib/test-suite-model'

/** A suite description is prose an author wrote for the next reader, and some
 * of them run to nine lines — enough to push the first test off the screen.
 * Two lines is the summary; the rest is one click away. */
function Description({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="flex flex-col items-start">
      <p className={`text-muted-foreground text-sm ${expanded ? '' : 'line-clamp-2'}`}>{text}</p>
      <button
        type="button"
        className="text-muted-foreground hover:text-foreground text-xs underline-offset-2 hover:underline"
        onClick={() => setExpanded((current) => !current)}
      >
        {expanded ? 'Show less' : 'Show more'}
      </button>
    </div>
  )
}

/** One suite: its own settings and its tests, each with the last run folded in
 * beside it. The suite is a container, so it gets a header and gets out of the
 * way — the detail belongs to the tests. */
export function SuiteCard({
  suiteName,
  suite,
  report,
  filter,
  problems,
  groups,
  nodes,
  enabled,
  canEdit,
  canValidate,
  running,
  onRun,
  onSettings,
  onAddTest,
  onEditTest,
  onDuplicateTest,
  onDeleteTest,
  onDeleteSuite,
}: {
  suiteName: string
  suite: TestSuite
  report: SuiteReport | undefined
  filter: ResultFilter
  problems: readonly SuiteProblem[]
  groups: ReadonlyMap<string, readonly string[]>
  nodes: readonly string[]
  enabled: boolean
  canEdit: boolean
  canValidate: boolean
  running: boolean
  onRun: (suite: string) => void
  onSettings: (suite: string) => void
  onAddTest: (suite: string) => void
  onEditTest: (suite: string, test: string) => void
  onDuplicateTest: (suite: string, test: string) => void
  onDeleteTest: (suite: string, test: string) => void
  onDeleteSuite: (suite: string) => void
}) {
  const outcomes = outcomesByTest(report)
  const status = suiteStatus(report)
  const orphans = orphanedTests(suite, report)
  const entries = Object.entries(suite.tests)
  const shown = entries.filter(([testName]) =>
    matchesFilter(outcomes.get(testName) ?? NOT_RUN, filter),
  )

  // A suite that contributes nothing to the current filter shrinks to a line.
  // It used to render its whole header, badges, description and Add-test
  // button in order to say "nothing here" — four hundred pixels of answer to a
  // question nobody asked.
  if (filter !== 'all' && shown.length === 0) {
    return (
      <Card className="py-3">
        <CardHeader className="gap-0">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">{suiteName}</span>
            <StageBadge stage={suite.stage} />
            {status !== 'not-run' && <SuiteStatusBadge status={status} />}
            <span className="text-muted-foreground text-xs">
              {entries.length} test{entries.length === 1 ? '' : 's'}, none matching this filter
            </span>
          </div>
        </CardHeader>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="gap-2">
        <div className="flex items-start gap-2">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
            <h3 className="text-base font-medium">{suiteName}</h3>
            <StageBadge stage={suite.stage} />
            {status !== 'not-run' && <SuiteStatusBadge status={status} />}
            <span className="text-muted-foreground text-xs">
              {entries.length} test{entries.length === 1 ? '' : 's'}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-1">
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
            {canEdit && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`More actions for ${suiteName}`}
                  >
                    <MoreHorizontal className="size-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => onSettings(suiteName)}>
                    Suite settings
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => onAddTest(suiteName)}>
                    Add test
                  </DropdownMenuItem>
                  <DropdownMenuItem variant="destructive" onSelect={() => onDeleteSuite(suiteName)}>
                    Delete suite
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        </div>
        {suite.description !== '' && <Description text={suite.description} />}
        <p className="text-muted-foreground text-xs">
          {report === undefined ? (
            'Never run.'
          ) : (
            <span title={formatDateTime(report.ran_at)}>
              {tallyLine(reportTally(report))} · {formatAgo(report.ran_at)}
            </span>
          )}
        </p>
        {orphans.length > 0 && (
          <p className="text-muted-foreground text-xs">
            The last run also covered {orphans.join(', ')}, which this suite no longer defines.
          </p>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {entries.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            This suite has no tests{canEdit ? ' — add one from the suite menu.' : '.'}
          </p>
        ) : (
          shown.map(([testName, test]) => (
            <TestCard
              key={testName}
              suiteName={suiteName}
              testName={testName}
              test={test}
              outcome={outcomes.get(testName) ?? NOT_RUN}
              groups={groups}
              nodes={nodes}
              blocked={problems.some(
                (problem) =>
                  problem.severity === 'error' &&
                  problem.suite === suiteName &&
                  problem.test === testName,
              )}
              canEdit={canEdit}
              onEdit={() => onEditTest(suiteName, testName)}
              onDuplicate={() => onDuplicateTest(suiteName, testName)}
              onDelete={() => onDeleteTest(suiteName, testName)}
            />
          ))
        )}
        {canEdit && entries.length > 0 && filter === 'all' && (
          <Button
            variant="outline"
            size="sm"
            className="self-start"
            onClick={() => onAddTest(suiteName)}
          >
            <Plus className="size-3.5" />
            Add test
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
