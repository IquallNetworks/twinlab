import { useState } from 'react'

import { TestCaseEditor } from '@/components/lab/test-case-editor'
import type { Suites } from '@/components/lab/tests/use-save-suites'
import { useSaveSuites } from '@/components/lab/tests/use-save-suites'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { TestCase, TestSuite, ValidationTest } from '@/lib/schemas'
import {
  caseEntries,
  isDeviceKeyed,
  resolveTargets,
  toDeviceKeyed,
  toSharedCase,
  validateSuites,
} from '@/lib/test-suite-model'
import type { SuiteAuthoring } from '@/lib/use-suite-authoring'

/** Which nodes the test runs on. Three selectors unioned (delta 32), because a
 * bare node list silently stops covering a lab that grows. */
function TargetPicker({
  test,
  patch,
  authoring,
}: {
  test: ValidationTest
  patch: (change: Partial<ValidationTest>) => void
  authoring: SuiteAuthoring
}) {
  const { nodes, groups, deviceByNode } = authoring
  const groupNames = [...groups.keys()]
  const targets = resolveTargets(test, nodes, groups)

  return (
    <div className="flex flex-col gap-1.5">
      <Label>Runs on</Label>
      <Select
        value={test.all_nodes ? 'all' : 'selected'}
        onValueChange={(value) =>
          patch(
            value === 'all' ? { all_nodes: true, groups: [], nodes: [] } : { all_nodes: false },
          )
        }
      >
        <SelectTrigger size="sm" className="w-72" aria-label="Runs on">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Every node in the lab</SelectItem>
          <SelectItem value="selected">Selected groups and nodes</SelectItem>
        </SelectContent>
      </Select>

      {test.all_nodes ? (
        <p className="text-muted-foreground text-xs">
          Stays correct as the lab grows — a node added later is tested too.
        </p>
      ) : nodes.length === 0 ? (
        <p className="text-muted-foreground text-xs">
          The lab has no definition yet — nodes and groups will be offered once it does.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {groupNames.length > 0 && (
            <div className="flex flex-col gap-1">
              <span className="text-muted-foreground text-xs">Groups</span>
              <div className="flex flex-wrap gap-3">
                {groupNames.map((group) => {
                  const id = `test-group-${group}`
                  return (
                    <div key={group} className="flex items-center gap-1.5 text-sm">
                      <Checkbox
                        id={id}
                        checked={test.groups.includes(group)}
                        onCheckedChange={(checked) =>
                          patch({
                            groups:
                              checked === true
                                ? [...test.groups, group]
                                : test.groups.filter((g) => g !== group),
                          })
                        }
                      />
                      <Label htmlFor={id} className="font-mono text-xs font-normal">
                        {group}
                      </Label>
                      <span className="text-muted-foreground text-xs">
                        {(groups.get(group) ?? []).length} nodes
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
          <div className="flex flex-col gap-1">
            <span className="text-muted-foreground text-xs">Nodes</span>
            <div className="flex flex-wrap gap-3">
              {nodes.map((node) => {
                // id + htmlFor, not a wrapping <label>: a radix checkbox is a
                // button, which a bare label does not name.
                const id = `test-node-${node}`
                const viaGroup = test.groups.some((g) => (groups.get(g) ?? []).includes(node))
                return (
                  <div key={node} className="flex items-center gap-1.5 text-sm">
                    <Checkbox
                      id={id}
                      checked={test.nodes.includes(node) || viaGroup}
                      // Already selected by a group: unticking it here would do
                      // nothing, so say why rather than lie.
                      disabled={viaGroup}
                      onCheckedChange={(checked) =>
                        patch({
                          nodes:
                            checked === true
                              ? [...test.nodes, node]
                              : test.nodes.filter((n) => n !== node),
                        })
                      }
                    />
                    <Label
                      htmlFor={id}
                      className="font-mono text-xs font-normal"
                      title={viaGroup ? 'Selected by a group above' : undefined}
                    >
                      {node}
                    </Label>
                    <span className="text-muted-foreground text-xs">{deviceByNode.get(node)}</span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}
      {/* The resolution, but only when it is not already on screen: with a
          group selected the union is worth spelling out, with three ticked
          boxes it just repeats them. */}
      {targets.length === 0 ? (
        <p className="text-destructive text-xs">Selects no nodes — this test would not run.</p>
      ) : (
        (test.all_nodes || test.groups.length > 0) && (
          <p className="text-muted-foreground text-xs">Runs on {targets.join(', ')}</p>
        )
      )}
    </div>
  )
}

/** Edit ONE test. The modal used to hold the whole suite map behind a rail,
 * which meant the dialog carried the navigation as well as the work; the Tests
 * tab is the navigation now, so this is only ever about the test you clicked.
 *
 * The draft is local, so Cancel discards. Save PUTs the whole map with this
 * test merged in — the wire has no partial verb.
 *
 * It also CREATES: a new suite and a new test both arrive here as `initial`
 * values that exist nowhere yet, and are written on the same Save as the test
 * itself. That is not a nicety — a blank test has no command, and the API
 * rightly refuses one, so saving a shell first and filling it in after is not
 * a flow that exists. */
export function TestEditDialog({
  labName,
  suiteName,
  testName,
  suites,
  initialSuite,
  initialTest,
  authoring,
  onClose,
}: {
  labName: string
  suiteName: string
  testName: string
  suites: Suites
  /** The suite being created — absent from `suites` until this Save. */
  initialSuite?: TestSuite
  /** The test being created, likewise. */
  initialTest?: ValidationTest
  authoring: SuiteAuthoring
  onClose: () => void
}) {
  const suite = suites[suiteName] ?? initialSuite
  const stored = suite?.tests[testName] ?? initialTest
  const [name, setName] = useState(testName)
  const [test, setTest] = useState<ValidationTest | undefined>(stored)
  const [caseDevice, setCaseDevice] = useState<string | null>(null)
  const save = useSaveSuites(labName, onClose)

  if (suite === undefined || test === undefined) return null

  const patch = (change: Partial<ValidationTest>): void => setTest({ ...test, ...change })

  const targets = resolveTargets(test, authoring.nodes, authoring.groups)
  const entries = caseEntries(test.run)
  const keyed = isDeviceKeyed(test.run)
  const active = keyed
    ? (entries.find((entry) => entry.device === caseDevice) ?? entries[0])
    : entries[0]

  // Which devices this case must be legal for: its own when device-keyed, else
  // every targeted node's — the same rule the server's mode check applies.
  const targetDevices = keyed
    ? active?.device != null
      ? [active.device]
      : []
    : targets
        .map((node) => authoring.deviceByNode.get(node))
        .filter((device): device is string => device !== undefined)
  const devices = authoring.catalog.filter((device) => targetDevices.includes(device.device))
  const labDevices = [...new Set(authoring.deviceByNode.values())]

  const setCase = (next: TestCase): void => {
    if (!keyed) {
      patch({ run: next })
      return
    }
    const device = active?.device
    if (device == null) return
    patch({ run: { ...(test.run as Record<string, TestCase>), [device]: next } })
  }

  // Validate the draft in place: the same call the whole map gets, over a map
  // holding just this test, so the gates cannot drift from the tab's.
  const problems = validateSuites(
    { [suiteName]: { ...suite, tests: { [name]: test } } },
    authoring.context,
  ).filter((problem) => problem.test === name)
  const collision = name !== testName && Object.hasOwn(suite.tests, name)
  const blocked = collision || problems.some((problem) => problem.severity === 'error')

  function onSave(): void {
    if (test === undefined || suite === undefined) return
    // Rename in PLACE: a test's name is its identity, and rebuilding the map
    // would reorder the suite under the author's cursor. A test that is not in
    // the map yet — a new one, or one deleted from another session while this
    // dialog was open — lands at the end rather than being dropped.
    const tests: Record<string, ValidationTest> = {}
    let placed = false
    for (const [key, value] of Object.entries(suite.tests)) {
      if (key === testName) {
        tests[name] = test
        placed = true
      } else {
        tests[key] = value
      }
    }
    if (!placed) tests[name] = test
    save.mutate({ ...suites, [suiteName]: { ...suite, tests } })
  }

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      {/* A test in progress is real work, and a stray click on the overlay
          would discard it silently. Cancel and the X are the deliberate ways
          out; Escape still works, because it is not the accident. */}
      <DialogContent
        className="flex max-h-[85vh] flex-col sm:max-w-5xl"
        onInteractOutside={(event) => event.preventDefault()}
      >
        <DialogHeader>
          {/* The DRAFT name, not the stored one: a rename is an edit to the
              thing being edited, so the title should follow it. */}
          <DialogTitle>
            {suiteName} · {name === '' ? testName : name}
          </DialogTitle>
          <DialogDescription>
            Commands and expectations may template lab facts — type{' '}
            <span className="font-mono">{'{{'}</span> in the command for the namespace. Try runs the
            case without saving it.
          </DialogDescription>
        </DialogHeader>

        {/* Two columns, because the ASSERTION is the point of the dialog and it
            used to sit below the fold of a single scrolling stack — under the
            name, the wait, the description and a node picker — with Try below
            that again. What the test is stays on the left; what it does is on
            the right, both on screen at once. */}
        <div className="grid min-h-0 flex-1 gap-6 overflow-y-auto pr-1 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
          <div className="flex flex-col gap-4">
            <div className="grid gap-3 grid-cols-[minmax(0,1fr)_6rem]">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="test-name">Test name</Label>
                <Input
                  id="test-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="test-wait">Wait (s)</Label>
                <Input
                  id="test-wait"
                  type="number"
                  min={0}
                  max={600}
                  value={test.wait}
                  onChange={(event) => patch({ wait: Number(event.target.value) })}
                />
              </div>
            </div>
            {collision && (
              <span className="text-destructive -mt-2 text-xs">
                This suite already has a test called “{name}”
              </span>
            )}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="test-description">Description</Label>
              <Textarea
                id="test-description"
                rows={2}
                value={test.description}
                onChange={(event) => patch({ description: event.target.value })}
                placeholder="what this proves"
              />
            </div>

            <TargetPicker test={test} patch={patch} authoring={authoring} />
          </div>

          <div className="flex flex-col gap-4 lg:border-l lg:pl-6">
            <div className="flex flex-wrap items-center gap-2">
            <Label className="font-normal">Case</Label>
            <Select
              value={keyed ? 'keyed' : 'shared'}
              onValueChange={(value) =>
                patch({
                  run:
                    value === 'keyed'
                      ? toDeviceKeyed(test.run, labDevices.length > 0 ? labDevices : ['vyos'])
                      : toSharedCase(test.run),
                })
              }
            >
              <SelectTrigger size="sm" className="w-56" aria-label="Case form">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="shared">One case for every node</SelectItem>
                <SelectItem value="keyed">A case per device</SelectItem>
              </SelectContent>
            </Select>
            {keyed && <span className="text-muted-foreground text-xs">for device</span>}
            {keyed && (
              <Select value={active?.device ?? ''} onValueChange={setCaseDevice}>
                <SelectTrigger size="sm" className="w-40" aria-label="Case device">
                  <SelectValue placeholder="Device" />
                </SelectTrigger>
                <SelectContent>
                  {entries.map((entry) => (
                    <SelectItem key={entry.device ?? ''} value={entry.device ?? ''}>
                      {entry.device}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
              {keyed && (
                <span className="text-muted-foreground text-xs">
                  A node whose device has no case is skipped, not failed.
                </span>
              )}
            </div>

            {active !== undefined && (
              <TestCaseEditor
                key={active.device ?? 'shared'}
                labName={labName}
                testCase={active.testCase}
                onChange={setCase}
                nodes={targets}
                devices={devices}
                deployed={authoring.deployed}
                facts={authoring.facts}
              />
            )}

            {problems.length > 0 && (
              <div className="flex flex-col gap-1 rounded-md border p-2 text-xs">
                {problems.map((problem, index) => (
                  <p
                    key={`${problem.field}.${index}`}
                    className={
                      problem.severity === 'error' ? 'text-destructive' : 'text-muted-foreground'
                    }
                  >
                    <Badge variant={problem.severity === 'error' ? 'destructive' : 'secondary'}>
                      {problem.severity}
                    </Badge>{' '}
                    <span className="font-mono">{problem.field}</span> — {problem.message}
                  </p>
                ))}
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={onSave}
            disabled={save.isPending || blocked}
            title={blocked ? 'Fix the errors above first' : undefined}
          >
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
