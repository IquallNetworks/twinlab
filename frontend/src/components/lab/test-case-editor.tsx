import type { CompletionContext, CompletionResult } from '@codemirror/autocomplete'
import { useMutation } from '@tanstack/react-query'
import { useCallback, useState } from 'react'

import { CodeEditor } from '@/components/code-editor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { api } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import type { CatalogDevice } from '@/lib/device-catalog'
import type { TestCase, TestCaseDraft, TestCaseDryRunResult } from '@/lib/schemas'
import { completionRequest, factCompletions, factRoot } from '@/lib/fact-completions'
import { MATCHER_KINDS, matcherKind, withMatcher, type MatcherKind } from '@/lib/test-suite-model'

/** The CodeMirror adapter over the pure completion logic. Kept here rather
 * than in lib/ so `fact-completions.ts` stays editor-free and checkable. */
function useFactCompletions(
  facts: Record<string, Record<string, unknown>> | undefined,
  representative: string | undefined,
): (context: CompletionContext) => CompletionResult | null {
  return useCallback(
    (context: CompletionContext): CompletionResult | null => {
      if (facts === undefined) return null
      const before = context.state.sliceDoc(0, context.pos)
      const request = completionRequest(before)
      if (request === null) return null
      const options = factCompletions(request, factRoot(facts, representative))
      if (options.length === 0) return null
      return {
        from: request.from,
        options: options.map((option) => ({
          label: option.label,
          detail: option.detail,
          // A container gets its dot for free: the next level is the point.
          apply: option.container ? option.label + '.' : option.label,
        })),
      }
    },
    [facts, representative],
  )
}

const MATCHER_LABELS: Record<MatcherKind, string> = {
  contains: 'Output contains',
  not_contains: 'Output does not contain',
  matches: 'Output matches (regex)',
  compare: 'Parsed data compares',
}

/** The probe (delta 31): run this exact case, unsaved, and show what it did.
 *
 * The reason it exists is the last block below — `parsed`. A `compare` asserts
 * over PARSED data, so writing one has meant predicting the shape TextFSM or
 * `vtysh … json` produces; a suite run computes that structure and throws it
 * away. Here it is on screen, next to the raw output it came from. */
function DryRunPanel({
  labName,
  testCase,
  nodes,
  enabled,
}: {
  labName: string
  testCase: TestCase
  nodes: readonly string[]
  enabled: boolean
}) {
  const [node, setNode] = useState(nodes[0] ?? '')
  const [result, setResult] = useState<TestCaseDryRunResult | null>(null)
  const target = nodes.includes(node) ? node : (nodes[0] ?? '')

  const tryIt = useMutation({
    mutationFn: () => {
      // The expectation rides along only when it is complete — otherwise the
      // probe answers the first question ("what does this print?") instead of
      // failing on a matcher that is still being written.
      const draft: TestCaseDraft = {
        command: testCase.command,
        mode: testCase.mode ?? 'shell',
        interactive: testCase.interactive ?? false,
        ...(testCase.parse != null ? { parse: testCase.parse } : {}),
        ...(matcherKind(testCase.expect) !== null ? { expect: testCase.expect } : {}),
      }
      return api.dryRunTestCase(labName, target, draft)
    },
    onSuccess: setResult,
    onError: (err) => toastError(err, 'Could not run the case'),
  })

  return (
    <div className="rounded-md border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={target} onValueChange={setNode} disabled={nodes.length === 0}>
          <SelectTrigger className="w-40" size="sm" aria-label="Try on node">
            <SelectValue placeholder="Node" />
          </SelectTrigger>
          <SelectContent>
            {nodes.map((name) => (
              <SelectItem key={name} value={name}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          onClick={() => tryIt.mutate()}
          disabled={!enabled || target === '' || testCase.command.trim() === '' || tryIt.isPending}
          title={enabled ? undefined : 'Try runs against a deployed lab'}
        >
          {tryIt.isPending ? 'Running…' : 'Try'}
        </Button>
        <span className="text-muted-foreground text-xs">
          Runs this case without saving it — nothing is stored.
        </span>
      </div>

      {result !== null && (
        <div className="mt-3 flex flex-col gap-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            {result.status != null && (
              <Badge variant={result.status === 'pass' ? 'default' : 'destructive'}>
                {result.status}
              </Badge>
            )}
            <span className="text-muted-foreground">
              {result.node} · {result.device} · {result.elapsed_ms} ms
            </span>
          </div>
          {result.detail !== '' && <p className="text-muted-foreground">{result.detail}</p>}
          {/* The ADAPTED command: rendered from facts and rewritten for the
              device's CLI, so it is what actually ran — and what to paste. */}
          <div>
            <p className="text-muted-foreground mb-1">Command</p>
            <pre className="bg-muted/50 overflow-auto rounded p-2 font-mono">{result.command}</pre>
          </div>
          <div>
            <p className="text-muted-foreground mb-1">Output</p>
            <pre className="bg-muted/50 max-h-48 overflow-auto rounded p-2 font-mono">
              {result.output.trim() === '' ? 'No output.' : result.output}
            </pre>
          </div>
          {result.parse_error != null && (
            <p className="text-destructive">Parse failed: {result.parse_error}</p>
          )}
          {result.parsed != null && (
            <div>
              <p className="text-muted-foreground mb-1">
                Parsed — write the <span className="font-mono">compare</span> against this
              </p>
              <pre className="bg-muted/50 max-h-48 overflow-auto rounded p-2 font-mono">
                {JSON.stringify(result.parsed, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** One case: the command, how it is interpreted, how its output is parsed, and
 * what is asserted. Every rule the server enforces is a control here rather
 * than a 422 later — the matcher is a single choice, and `parse` follows the
 * matcher because compare and parse require each other both ways. */
export function TestCaseEditor({
  labName,
  testCase,
  onChange,
  nodes,
  devices,
  deployed,
  facts,
}: {
  labName: string
  testCase: TestCase
  onChange: (next: TestCase) => void
  /** The nodes this case will run on — the Try target list, and what decides
   * which devices its `mode` has to be legal for. */
  nodes: readonly string[]
  /** The devices those nodes are, resolved against the catalog. */
  devices: readonly CatalogDevice[]
  deployed: boolean
  /** The lab's fact namespace, for command completion. Undefined until the
   * query settles, or on a lab with no definition — the field still works,
   * it just has nothing to offer. */
  facts?: Record<string, Record<string, unknown>>
}) {
  // `node` in a template is whichever node is executing; for completion the
  // first target stands in for all of them (the promised core is identical).
  const completions = useFactCompletions(facts, nodes[0])
  const kind = matcherKind(testCase.expect)
  const mode = testCase.mode ?? 'shell'
  // `cli` is only offered where every target device has a CLI to reach: the
  // server 422s otherwise, and the reason is worth saying before the save.
  const noCli = devices.filter((device) => !device.cliMode)
  const cliBlocked = noCli.length > 0
  const noTextfsm = devices.filter((device) => !device.textfsm)

  const patch = (change: Partial<TestCase>): void => onChange({ ...testCase, ...change })

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="case-command">Command</Label>
        {/* A CodeMirror field rather than a textarea, for one reason: inside
            `{{ }}` it completes the lab's own fact namespace, so a path is
            picked from what the lab actually has instead of transcribed from
            the Facts dialog. No gutter — this is a one-line field. */}
        <div id="case-command" aria-label="Command">
          <CodeEditor
            value={testCase.command}
            onChange={(command) => patch({ command })}
            language="jinja2"
            gutter={false}
            completions={completions}
            placeholder="ip -o link show lo"
            className="min-h-9"
          />
        </div>
        <p className="text-muted-foreground text-xs">
          Templates lab facts — type <span className="font-mono">{'{{'}</span> and the namespace
          completes, e.g. <span className="font-mono">{'{{ nodes.r2.loopback.ipv4 | address }}'}</span>.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="case-mode">Command language</Label>
          <Select value={mode} onValueChange={(value) => patch({ mode: value as 'shell' | 'cli' })}>
            <SelectTrigger id="case-mode" aria-label="Command language">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="shell">Shell — the container&apos;s shell</SelectItem>
              <SelectItem value="cli" disabled={cliBlocked}>
                CLI — the device&apos;s own CLI
              </SelectItem>
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-xs">
            {cliBlocked
              ? `${noCli.map((d) => d.label).join(', ')} has no CLI of its own — its shell is the interface.`
              : 'The exec transport lands in the shell, so a NOS command needs CLI mode.'}
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="case-parse">Parse output as</Label>
          <Select
            value={testCase.parse ?? 'none'}
            onValueChange={(value) => {
              const parse = value === 'none' ? null : (value as 'json' | 'textfsm')
              // The coupling, enforced rather than validated: parsed data is
              // only asserted with compare, and compare needs parsed data.
              if (parse === null && kind === 'compare') {
                patch({ parse, expect: withMatcher(testCase.expect, 'contains') })
              } else if (parse !== null && kind !== 'compare') {
                patch({ parse, expect: withMatcher(testCase.expect, 'compare') })
              } else {
                patch({ parse })
              }
            }}
          >
            <SelectTrigger id="case-parse" aria-label="Parse output as">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">Raw output</SelectItem>
              <SelectItem value="json">JSON</SelectItem>
              <SelectItem value="textfsm">TextFSM</SelectItem>
            </SelectContent>
          </Select>
          {testCase.parse === 'textfsm' && noTextfsm.length > 0 && (
            <p className="text-muted-foreground text-xs">
              {noTextfsm.map((d) => d.label).join(', ')} has no TextFSM template set — this case
              will error there.
            </p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Checkbox
          id="case-interactive"
          checked={testCase.interactive ?? false}
          onCheckedChange={(checked) => patch({ interactive: checked === true })}
        />
        <Label htmlFor="case-interactive" className="font-normal">
          Interactive session
        </Label>
        <span className="text-muted-foreground text-xs">
          For commands a one-shot exec truncates, like a timed ping.
        </span>
      </div>

      <DryRunPanel labName={labName} testCase={testCase} nodes={nodes} enabled={deployed} />

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="case-matcher">Assertion</Label>
        <Select
          value={kind ?? 'contains'}
          onValueChange={(value) => {
            const next = value as MatcherKind
            patch({
              expect: withMatcher(testCase.expect, next),
              // Same coupling from the other side.
              parse: next === 'compare' ? (testCase.parse ?? 'json') : null,
            })
          }}
        >
          <SelectTrigger id="case-matcher" aria-label="Assertion">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MATCHER_KINDS.map((matcher) => (
              <SelectItem key={matcher} value={matcher}>
                {MATCHER_LABELS[matcher]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {kind === 'compare' ? (
          <CodeEditor
            value={JSON.stringify(testCase.expect.compare ?? {}, null, 2)}
            onChange={(text) => {
              try {
                patch({ expect: { compare: JSON.parse(text) as Record<string, unknown> } })
              } catch {
                // Held in the editor until it parses; the lint gutter says why.
              }
            }}
            language="json"
            lint
            className="max-h-64 min-h-32"
          />
        ) : (
          <Input
            aria-label="Expected value"
            value={(kind === null ? '' : ((testCase.expect[kind] as string | null) ?? '')) || ''}
            onChange={(event) =>
              patch({ expect: { [kind ?? 'contains']: event.target.value } })
            }
            className="font-mono"
            placeholder={kind === 'matches' ? 'FULL/\\w+' : 'Full'}
          />
        )}
      </div>

    </div>
  )
}
