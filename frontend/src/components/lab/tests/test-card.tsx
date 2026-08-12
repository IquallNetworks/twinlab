import { ChevronDown, ChevronRight, MoreHorizontal, Pencil } from 'lucide-react'
import { useState } from 'react'

import { ResultDetail } from '@/components/lab/tests/result-detail'
import { StatusBadge, StatusIcon, statusTone } from '@/components/lab/tests/status-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { TestResult, ValidationTest } from '@/lib/schemas'
import { tallyLine, type TestOutcome } from '@/lib/test-results'
import { caseEntries, isDeviceKeyed, resolveTargets } from '@/lib/test-suite-model'

/** What the test targets, as chips. The point of showing it on the card is
 * that a target is a claim about the FUTURE — "all nodes" keeps covering a lab
 * that grows, a node list does not (delta 32) — so it belongs next to the
 * results rather than only inside the editor. */
function TargetChips({
  test,
  targets,
  groups,
}: {
  test: ValidationTest
  targets: readonly string[]
  groups: ReadonlyMap<string, readonly string[]>
}) {
  if (test.all_nodes) {
    return (
      <Badge variant="outline" title="A node added later is tested too">
        every node{targets.length > 0 ? ` (${targets.length})` : ''}
      </Badge>
    )
  }
  return (
    <>
      {test.groups.map((group) => (
        <Badge
          key={`g:${group}`}
          variant="outline"
          title={`group — ${(groups.get(group) ?? []).join(', ') || 'no members'}`}
        >
          group {group}
        </Badge>
      ))}
      {test.nodes.map((node) => (
        <Badge key={`n:${node}`} variant="outline" className="font-mono">
          {node}
        </Badge>
      ))}
    </>
  )
}

/** The case, as one readable line per device: the command plus the flags that
 * change how it is interpreted. Enough to recognise the test without opening
 * it; the editor is one click away for anything more. */
function CaseSummary({ test }: { test: ValidationTest }) {
  const keyed = isDeviceKeyed(test.run)
  return (
    <div className="flex flex-col gap-1">
      {caseEntries(test.run).map((entry) => {
        const testCase = entry.testCase
        return (
          <div key={entry.device ?? 'shared'} className="flex flex-wrap items-center gap-1.5">
            {keyed && (
              <span className="text-muted-foreground shrink-0 font-mono text-[11px]">
                {entry.device}
              </span>
            )}
            <code className="bg-muted/50 min-w-0 truncate rounded px-1.5 py-0.5 font-mono text-[11px]">
              {testCase.command}
            </code>
            {testCase.mode === 'cli' && <Badge variant="secondary">cli</Badge>}
            {testCase.interactive === true && <Badge variant="secondary">interactive</Badge>}
            {testCase.parse != null && <Badge variant="secondary">{testCase.parse}</Badge>}
          </div>
        )
      })}
    </div>
  )
}

/** One node's verdict, as a pill that opens the result. A test that ran on
 * eight nodes is eight rows on the wire; here it is one row of pills, which is
 * how the question is actually asked ("which node failed?").
 *
 * The pill carries the node and nothing else. It used to carry the elapsed
 * time too, which put a number nobody asked for on every pill and made a row
 * of identical passes read as data; the timing lives on the opened result,
 * where it is the answer to a question someone is actually asking. */
function ResultPills({
  results,
  openNode,
  onToggle,
}: {
  results: readonly TestResult[]
  openNode: string | null
  onToggle: (node: string) => void
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {results.map((result) => (
        <Badge
          key={result.node}
          asChild
          variant="outline"
          className={`${statusTone(result.status)} ${openNode === result.node ? 'ring-ring ring-2' : ''}`}
        >
          <button
            type="button"
            onClick={() => onToggle(result.node)}
            aria-expanded={openNode === result.node}
            title={result.detail === '' ? result.status : result.detail}
          >
            <StatusIcon status={result.status} />
            <span className="font-mono">{result.node}</span>
          </button>
        </Badge>
      ))}
    </div>
  )
}

/** One test, with its last run. The unit of the Tests tab: a test is the thing
 * an author writes and an operator asks about, so it gets a card of its own
 * rather than being a row that expands into an undifferentiated list of
 * (test, node) pairs. */
export function TestCard({
  suiteName,
  testName,
  test,
  outcome,
  groups,
  nodes,
  blocked,
  canEdit,
  onEdit,
  onDuplicate,
  onDelete,
}: {
  suiteName: string
  testName: string
  test: ValidationTest
  outcome: TestOutcome
  groups: ReadonlyMap<string, readonly string[]>
  nodes: readonly string[]
  /** The test has a problem the PUT would reject — flagged here so it is
   * findable without opening every editor. */
  blocked: boolean
  canEdit: boolean
  onEdit: () => void
  onDuplicate: () => void
  onDelete: () => void
}) {
  const [openNode, setOpenNode] = useState<string | null>(null)
  // A run where every node passed has nothing to point at, so the pills start
  // folded behind their own tally; anything else opens showing them.
  const clean = outcome.status === 'pass'
  const [showPills, setShowPills] = useState(false)
  const targets = resolveTargets(test, nodes, groups)
  const open = outcome.results.find((result) => result.node === openNode)
  const pillsOpen = !clean || showPills

  return (
    <div className="rounded-md border p-3" data-testid={`test-${suiteName}-${testName}`}>
      {/* The actions are a column of their own, not a wrap participant: with
          `flex-wrap` on the row they dropped under a two-line description on
          some cards and stayed top-right on others. */}
      <div className="flex items-start gap-2">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{testName}</span>
            {outcome.status === null ? (
              <Badge variant="outline" className="text-muted-foreground">
                not run
              </Badge>
            ) : (
              <StatusBadge status={outcome.status} />
            )}
            {blocked && (
              <Badge variant="destructive" title="This test would be rejected on save">
                needs fixing
              </Badge>
            )}
            {test.wait > 0 && (
              <span className="text-muted-foreground text-xs">waits {test.wait}s</span>
            )}
          </div>
          {test.description !== '' && (
            <p className="text-muted-foreground text-sm">{test.description}</p>
          )}
        </div>
        {canEdit && (
          <div className="flex shrink-0 items-center gap-1">
            <Button variant="outline" size="sm" onClick={onEdit}>
              <Pencil className="size-3.5" />
              Edit
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label={`More actions for ${testName}`}>
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={onDuplicate}>Duplicate</DropdownMenuItem>
                <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="text-muted-foreground text-xs">Runs on</span>
        <TargetChips test={test} targets={targets} groups={groups} />
      </div>

      <div className="mt-2">
        <CaseSummary test={test} />
      </div>

      <div className="mt-3 border-t pt-2">
        {outcome.status === null ? (
          <p className="text-muted-foreground text-xs">
            No results — run the suite to see what this does.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {clean ? (
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground -my-1 flex w-fit items-center gap-1 py-1 text-xs"
                onClick={() => setShowPills((current) => !current)}
                aria-expanded={showPills}
              >
                {showPills ? (
                  <ChevronDown className="size-3.5" />
                ) : (
                  <ChevronRight className="size-3.5" />
                )}
                {tallyLine(outcome.tally)}
              </button>
            ) : (
              <p className="text-muted-foreground text-xs">{tallyLine(outcome.tally)}</p>
            )}
            {pillsOpen && (
              <ResultPills
                results={outcome.results}
                openNode={openNode}
                onToggle={(node) => setOpenNode((current) => (current === node ? null : node))}
              />
            )}
            {pillsOpen && open !== undefined && (
              <div className="bg-muted/20 rounded-md border p-2">
                <ResultDetail result={open} />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
