import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useBlocker } from '@tanstack/react-router'
import { X } from 'lucide-react'
import { useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { toast } from 'sonner'

import {
  builderReducer,
  initialBuilderState,
  type BuilderAction,
} from '@/components/lab/build/build-state'
import { BuilderCanvas } from '@/components/lab/build/builder-canvas'
import { DefinitionEditor } from '@/components/lab/build/definition-editor'
import { Inspector } from '@/components/lab/build/inspector'
import { TopologyCanvas } from '@/components/lab/topology/topology-canvas'
import { loadLayout, savePositions, type SavedPositions } from '@/components/lab/topology/layout-store'
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
import { api, ApiError } from '@/lib/api'
import { emitBuildDoc, emptyBuildDoc, parseBuildDoc } from '@/lib/build-doc'
import { PERM_LAB_EDIT } from '@/lib/lab-permissions'
import { labQueryOptions, labsQueryOptions } from '@/lib/queries'
import type { LabDetail } from '@/lib/schemas'
import { parseTopology } from '@/lib/topology'

type Mode = 'visual' | 'text'

/** The Build tab owns definition editing, in two modes: Visual (the guided
 * builder over the strict BuildDoc subset) and Text (the full-syntax escape
 * hatch). The stored definition stays the sole source of truth — Save PUTs
 * it and the dry `netlab create` server-side stays the real validator. */
export function BuildTab({ name }: { name: string }) {
  // Same cached query the layout resolved; never pending in practice.
  const { data: lab } = useQuery(labQueryOptions(name))
  if (!lab) return null
  if (!lab.permissions.includes(PERM_LAB_EDIT)) {
    return (
      <p className="text-sm text-muted-foreground">
        Editing this lab&apos;s definition requires the lab:edit permission.
      </p>
    )
  }
  return <BuildTabInner lab={lab} />
}

function BuildTabInner({ lab }: { lab: LabDetail }) {
  const name = lab.name
  const queryClient = useQueryClient()

  // The strict gate over the stored definition. A fresh lab (no definition)
  // is an empty, fully-representable doc.
  const parsed = useMemo(
    () =>
      lab.definition === null
        ? ({ ok: true, doc: emptyBuildDoc() } as const)
        : parseBuildDoc(lab.definition),
    [lab.definition],
  )

  const [mode, setMode] = useState<Mode>(parsed.ok ? 'visual' : 'text')
  const [state, rawDispatch] = useReducer(
    builderReducer,
    undefined,
    () => initialBuilderState(parsed.ok ? parsed.doc : emptyBuildDoc()),
  )
  const [textDirty, setTextDirty] = useState(false)
  const dirty = mode === 'visual' ? state.dirty : textDirty

  // Manual layout, shared with the Topology tab via the same per-lab store.
  const [positions, setPositionsState] = useState<SavedPositions>(() => loadLayout(name) ?? {})
  const positionsRef = useRef(positions)
  positionsRef.current = positions
  const onPositions = (next: SavedPositions, persist: boolean) => {
    setPositionsState(next)
    if (persist) savePositions(name, next)
  }

  // Renames migrate the saved position to the new node id before the reducer
  // rewrites the doc — otherwise the renamed node would jump to a dagre spot.
  const dispatch = (action: BuilderAction) => {
    if (action.type === 'rename-node') {
      const current = positionsRef.current[action.from]
      if (current !== undefined) {
        const next = { ...positionsRef.current, [action.to]: current }
        delete next[action.from]
        onPositions(next, true)
      }
    }
    rawDispatch(action)
  }

  // Keep the builder in sync with server-side changes, but only while clean:
  // a dirty builder is last-write-wins (as the old edit dialog was) with an
  // explicit hint instead of a silent draft wipe.
  const [syncedDefinition, setSyncedDefinition] = useState(lab.definition)
  useEffect(() => {
    if (lab.definition === syncedDefinition || dirty) return
    setSyncedDefinition(lab.definition)
    const next =
      lab.definition === null ? ({ ok: true, doc: emptyBuildDoc() } as const) : parseBuildDoc(lab.definition)
    if (next.ok) rawDispatch({ type: 'reset', doc: next.doc })
  }, [lab.definition, syncedDefinition, dirty])
  const serverChanged = dirty && lab.definition !== syncedDefinition

  const [saveError, setSaveError] = useState<ApiError | null>(null)

  const save = useMutation({
    mutationFn: (definition: string) => api.updateLabDefinition(name, definition),
    onSuccess: (updated) => {
      // The PUT response IS the fresh record (server-rewritten definition
      // with the injected name/addressing) — seed the cache from it.
      queryClient.setQueryData(labQueryOptions(name).queryKey, updated)
      void queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey })
      setSyncedDefinition(updated.definition)
      setSaveError(null)
      toast.success(`Definition saved. Deploy ${name} to apply it.`)
      if (updated.definition !== null) {
        const reparsed = parseBuildDoc(updated.definition)
        if (reparsed.ok) {
          rawDispatch({ type: 'reset', doc: reparsed.doc })
        } else {
          // Defensively unreachable: the server only injects whitelisted
          // keys. Fall back honestly rather than showing a stale canvas.
          setMode('text')
        }
      }
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === 'netlab_invalid') setSaveError(err)
      else toast.error(err instanceof Error ? err.message : 'Save failed')
    },
  })

  const emitted = useMemo(() => emitBuildDoc(state.doc), [state.doc])

  const saveVisual = () => {
    if (emitted.ok) save.mutate(emitted.yaml)
  }
  const saveText = async (text: string): Promise<boolean> => {
    try {
      await save.mutateAsync(text)
      return true
    } catch {
      return false // surfaced by onError
    }
  }

  // Mode switching discards the outgoing mode's draft — confirmed when dirty.
  const [pendingMode, setPendingMode] = useState<Mode | null>(null)
  const switchTo = (next: Mode) => {
    if (mode === 'visual') {
      rawDispatch({ type: 'reset', doc: parsed.ok ? parsed.doc : emptyBuildDoc() })
    }
    setTextDirty(false) // the editor unmounts; its draft dies with it
    setMode(next)
  }
  const requestMode = (next: Mode) => {
    if (next === mode) return
    if (dirty) setPendingMode(next)
    else switchTo(next)
  }

  const discardVisual = () => {
    rawDispatch({ type: 'reset', doc: parsed.ok ? parsed.doc : emptyBuildDoc() })
  }

  // Leaving the tab with unsaved changes: router blocker + tab-close guard.
  const blocker = useBlocker({ shouldBlockFn: () => dirty, withResolver: true })
  useEffect(() => {
    if (!dirty) return
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  const stderr = saveError?.extras?.['stderr']
  const gateBlocked = mode === 'visual' && !parsed.ok && !state.dirty
  const preview = useMemo(
    () => (gateBlocked && lab.definition !== null ? parseTopology(lab.definition) : null),
    [gateBlocked, lab.definition],
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Tabs value={mode} onValueChange={(value) => requestMode(value as Mode)}>
          <TabsList>
            <TabsTrigger value="visual">Visual</TabsTrigger>
            <TabsTrigger value="text">Text</TabsTrigger>
          </TabsList>
        </Tabs>
        {mode === 'visual' && (
          <div className="flex items-center gap-2">
            {serverChanged && (
              <span className="text-xs text-muted-foreground">
                Definition changed on the server — saving overwrites it.
              </span>
            )}
            {state.dirty && (
              <>
                <span className="font-mono text-xs text-muted-foreground">unsaved changes</span>
                <Button variant="outline" size="sm" onClick={discardVisual} disabled={save.isPending}>
                  Discard
                </Button>
              </>
            )}
            <Button
              size="sm"
              onClick={saveVisual}
              disabled={!state.dirty || !emitted.ok || save.isPending}
            >
              {save.isPending ? 'Saving…' : 'Save'}
            </Button>
          </div>
        )}
      </div>

      {mode === 'visual' && state.dirty && !emitted.ok && (
        <div className="rounded-[2px] border border-destructive/50 bg-card px-3 py-2 text-sm">
          <p className="text-destructive">Not saveable yet:</p>
          <ul className="mt-1 list-inside list-disc text-muted-foreground">
            {emitted.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </div>
      )}

      {saveError !== null && (
        <div className="rounded-[2px] border border-destructive/50 bg-card px-3 py-2 text-sm">
          <div className="flex items-start justify-between gap-2">
            <p className="text-destructive">netlab rejected the definition: {saveError.message}</p>
            <Button variant="ghost" size="icon-xs" title="Dismiss" onClick={() => setSaveError(null)}>
              <X className="size-3" />
            </Button>
          </div>
          {typeof stderr === 'string' && stderr !== '' && (
            <pre className="mt-2 max-h-56 overflow-auto rounded-[2px] bg-muted p-2 font-mono text-xs">
              {stderr}
            </pre>
          )}
        </div>
      )}

      {gateBlocked ? (
        <Card>
          <CardContent className="flex flex-col gap-3 pt-6">
            <p className="text-sm">
              This definition uses features the builder can&apos;t represent — edit it as text.
            </p>
            <ul className="list-inside list-disc text-sm text-muted-foreground">
              {!parsed.ok && parsed.reasons.map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
            <div>
              <Button variant="outline" size="sm" onClick={() => switchTo('text')}>
                Open text editor
              </Button>
            </div>
            {preview !== null && preview.nodes.length > 0 && (
              <div className="h-[max(20rem,calc(100vh-34rem))] rounded-[2px] border">
                <TopologyCanvas lab={lab} topology={preview} />
              </div>
            )}
          </CardContent>
        </Card>
      ) : mode === 'visual' ? (
        <div className="flex items-stretch gap-4">
          <Card className="min-w-0 flex-1 py-0">
            <CardContent className="p-0">
              <div className="h-[max(28rem,calc(100vh-24rem))]">
                <BuilderCanvas
                  state={state}
                  dispatch={dispatch}
                  positions={positions}
                  onPositions={onPositions}
                />
              </div>
            </CardContent>
          </Card>
          <aside className="w-80 shrink-0 overflow-y-auto rounded-[2px] border bg-card p-4">
            <Inspector state={state} dispatch={dispatch} />
          </aside>
        </div>
      ) : (
        <DefinitionEditor
          definition={lab.definition}
          saving={save.isPending}
          onSave={saveText}
          onDirtyChange={setTextDirty}
        />
      )}

      <AlertDialog open={pendingMode !== null} onOpenChange={(open) => !open && setPendingMode(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              Switching to the {pendingMode === 'text' ? 'text editor' : 'visual builder'} discards
              the changes you haven&apos;t saved.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Stay</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingMode !== null) switchTo(pendingMode)
                setPendingMode(null)
              }}
            >
              Discard and switch
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={blocker.status === 'blocked'}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Leave with unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              The definition changes you made here are not saved.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => blocker.status === 'blocked' && blocker.reset()}>
              Stay
            </AlertDialogCancel>
            <AlertDialogAction onClick={() => blocker.status === 'blocked' && blocker.proceed()}>
              Leave
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
