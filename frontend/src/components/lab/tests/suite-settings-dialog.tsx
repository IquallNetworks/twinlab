import { useState } from 'react'

import type { Suites } from '@/components/lab/tests/use-save-suites'
import { useSaveSuites } from '@/components/lab/tests/use-save-suites'
import { Button } from '@/components/ui/button'
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
import type { TestSuite } from '@/lib/schemas'
import { blankSuite, nameProblem } from '@/lib/test-suite-model'

/** A suite's own three fields — everything about it that is not a test. Small
 * on purpose: the suite is a container, and the work is in the tests it holds.
 *
 * The same dialog creates one, but a create does NOT save here: an empty suite
 * is rejected by the contract and a blank first test has no command, so the
 * suite is handed to the test editor and both are written on one Save. */
export function SuiteSettingsDialog({
  labName,
  suites,
  suiteName,
  onCreate,
  onClose,
}: {
  labName: string
  suites: Suites
  /** null = create a new suite. */
  suiteName: string | null
  /** Called instead of saving, when creating. */
  onCreate: (name: string, suite: TestSuite) => void
  onClose: () => void
}) {
  const existing = suiteName === null ? undefined : suites[suiteName]
  const [name, setName] = useState(suiteName ?? '')
  const [stage, setStage] = useState(existing?.stage ?? 'runtime')
  const [description, setDescription] = useState(existing?.description ?? '')
  const save = useSaveSuites(labName, onClose)

  const problem = nameProblem(name)
  const collision = name !== suiteName && Object.hasOwn(suites, name)
  const blocked = problem !== null || collision

  function onSave(): void {
    if (blocked) return
    if (suiteName === null) {
      onCreate(name, { stage, description, tests: {} })
      return
    }
    const previous = existing ?? blankSuite()
    // Rename in place so the list does not reorder under the author.
    const next = Object.fromEntries(
      Object.entries(suites).map(([key, value]) =>
        key === suiteName ? [name, { ...previous, stage, description }] : [key, value],
      ),
    )
    save.mutate(next)
  }

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{suiteName === null ? 'New suite' : `Suite ${suiteName}`}</DialogTitle>
          <DialogDescription>
            A suite groups tests and decides when they run. Config-time suites gate a configure; a
            runtime suite runs when you ask for it.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="suite-name">Name</Label>
            <Input
              id="suite-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="smoke"
            />
            {/* An untouched new-suite form is empty, not wrong — Create is
                disabled either way, so the message waits for a first keystroke. */}
            {name !== '' && problem !== null && (
              <span className="text-destructive text-xs">{problem}</span>
            )}
            {collision && (
              <span className="text-destructive text-xs">
                This lab already has a suite called “{name}”
              </span>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="suite-stage">Stage</Label>
            <Select value={stage} onValueChange={setStage}>
              <SelectTrigger id="suite-stage" className="w-full" aria-label="Stage">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="runtime">Runtime — on demand</SelectItem>
                <SelectItem value="config-time">Config-time — gates a configure</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="suite-description">Description</Label>
            <Input
              id="suite-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="what this suite proves"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={onSave} disabled={blocked || save.isPending}>
            {save.isPending ? 'Saving…' : suiteName === null ? 'Next: the first test' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
