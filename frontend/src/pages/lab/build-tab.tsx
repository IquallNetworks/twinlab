import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useBlocker } from '@tanstack/react-router'
import { FileCode2, X } from 'lucide-react'
import { useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { toast } from 'sonner'

import {
  canRedo,
  canUndo,
  historyReducer,
  initialHistory,
  nodeStamp,
  type BuilderAction,
  type NodeStamp,
} from '@/components/lab/build/build-state'
import { BuilderCanvas } from '@/components/lab/build/builder-canvas'
import { DefinitionEditor } from '@/components/lab/build/definition-editor'
import { Inspector } from '@/components/lab/build/inspector'
import { TopologyCanvas } from '@/components/lab/topology/topology-canvas'
import type { SavedPositions } from '@/components/lab/topology/flow-types'
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
import { emitBuildDoc, emptyBuildDoc, nextNodeName, parseBuildDoc } from '@/lib/build-doc'
import { toastError } from '@/lib/error-toast'
import type { GroupStyles } from '@/lib/group-colors'
import { PERM_LAB_EDIT } from '@/lib/lab-permissions'
import { labLayoutQueryOptions, labQueryOptions, labsQueryOptions } from '@/lib/queries'
import type { LabDetail } from '@/lib/schemas'
import { useDeviceCatalog } from '@/lib/use-device-catalog'
import { parseTopology } from '@/lib/topology'

type Mode = 'visual' | 'text'

/** The Build tab owns definition editing, in two modes: Visual (the guided
 * builder over the strict BuildDoc subset) and Text (the full-syntax escape
 * hatch). The stored definition stays the sole source of truth — Save PUTs
 * it and the dry `netlab create` server-side stays the real validator. */
export function BuildTab({ name }: { name: string }) {
  // Same cached query the layout resolved; never pending in practice.
  const { data: lab } = useQuery(labQueryOptions(name))
  // Waited for (settled, not necessarily live) so the parse gate and the
  // palette agree on ONE device list for the life of the mount.
  const catalog = useDeviceCatalog()
  // The shared arrangement (delta 19), waited for like the catalog so the
  // canvas seeds from it once instead of jumping when it resolves. An error
  // degrades to an empty arrangement — layout is presentational.
  const layoutQuery = useQuery(labLayoutQueryOptions(name))
  if (!lab || !catalog.ready || layoutQuery.isPending) return null
  if (!lab.permissions.includes(PERM_LAB_EDIT)) {
    return (
      <p className="text-sm text-muted-foreground">
        Editing this lab&apos;s definition requires the lab:edit permission.
      </p>
    )
  }
  return (
    <BuildTabInner
      lab={lab}
      knownDevices={catalog.devices.map((d) => d.device)}
      initialPositions={layoutQuery.data?.positions ?? {}}
      initialGroupStyles={layoutQuery.data?.groups ?? {}}
    />
  )
}

function BuildTabInner({
  lab,
  knownDevices,
  initialPositions,
  initialGroupStyles,
}: {
  lab: LabDetail
  knownDevices: string[]
  initialPositions: SavedPositions
  initialGroupStyles: GroupStyles
}) {
  const name = lab.name
  const queryClient = useQueryClient()

  // The strict gate over the stored definition. A fresh lab (no definition)
  // is an empty, fully-representable doc.
  const parsed = useMemo(
    () =>
      lab.definition === null
        ? ({ ok: true, doc: emptyBuildDoc(), notices: [] } as const)
        : parseBuildDoc(lab.definition, knownDevices),
    // knownDevices is settled for the mount's lifetime (BuildTab gates on it).
    [lab.definition, knownDevices],
  )

  const [mode, setMode] = useState<Mode>(parsed.ok ? 'visual' : 'text')
  const [history, rawDispatch] = useReducer(historyReducer, undefined, () =>
    initialHistory(parsed.ok ? parsed.doc : emptyBuildDoc()),
  )
  const state = history.present
  // The node clipboard: session-scoped and in-memory on purpose — this is a
  // builder affordance, not an OS clipboard integration (a BuildNode has no
  // sensible text/plain form, and reading the system clipboard needs a
  // permission prompt the copy does not deserve).
  const [clipboard, setClipboard] = useState<NodeStamp | null>(null)
  const [textDirty, setTextDirty] = useState(false)
  const dirty = mode === 'visual' ? state.dirty : textDirty

  // The shared manual layout (delta 19) + group styles (delta 20): seeded
  // from the server once (the outer component waits for the query), saved
  // back on every persisting change. PUT replaces the WHOLE resource and the
  // builder always hands over the complete maps, so stale ids prune
  // naturally. Failures surface but never block editing — presentational.
  const [positions, setPositionsState] = useState<SavedPositions>(initialPositions)
  const positionsRef = useRef(positions)
  positionsRef.current = positions
  const [groupStyles, setGroupStylesState] = useState<GroupStyles>(initialGroupStyles)
  const groupStylesRef = useRef(groupStyles)
  groupStylesRef.current = groupStyles
  const saveLayout = useMutation({
    mutationFn: (payload: { positions: SavedPositions; groups: GroupStyles }) =>
      api.putLabLayout(name, payload.positions, payload.groups),
    onSuccess: (stored) => {
      queryClient.setQueryData(labLayoutQueryOptions(name).queryKey, stored)
    },
    onError: (err) => toastError(err, 'Layout save failed'),
  })
  const persistLayout = () =>
    saveLayout.mutate({ positions: positionsRef.current, groups: groupStylesRef.current })
  const onPositions = (next: SavedPositions, persist: boolean) => {
    setPositionsState(next)
    positionsRef.current = next
    if (persist) persistLayout()
  }
  // The native color input fires continuously while the picker drags —
  // update the canvas immediately, debounce the PUT.
  const styleSaveTimer = useRef<number | null>(null)
  const onGroupColor = (group: string, color: string) => {
    const next = { ...groupStylesRef.current, [group]: { color } }
    setGroupStylesState(next)
    groupStylesRef.current = next
    if (styleSaveTimer.current !== null) window.clearTimeout(styleSaveTimer.current)
    styleSaveTimer.current = window.setTimeout(() => {
      styleSaveTimer.current = null
      persistLayout()
    }, 400)
  }

  // Renames migrate the saved position/style to the new id before the
  // reducer rewrites the doc — otherwise the renamed node would jump to a
  // dagre spot (and a renamed group would lose its color); deletes drop the
  // group's style so the stored map doesn't accumulate stale names.
  const dispatch = (action: BuilderAction) => {
    if (action.type === 'rename-node') {
      const current = positionsRef.current[action.from]
      if (current !== undefined) {
        const next = { ...positionsRef.current, [action.to]: current }
        delete next[action.from]
        onPositions(next, true)
      }
    }
    if (action.type === 'rename-group') {
      const style = groupStylesRef.current[action.from]
      if (style !== undefined) {
        const next = { ...groupStylesRef.current, [action.to]: style }
        delete next[action.from]
        setGroupStylesState(next)
        groupStylesRef.current = next
        persistLayout()
      }
    }
    if (action.type === 'delete-group' && groupStylesRef.current[action.name] !== undefined) {
      const next = { ...groupStylesRef.current }
      delete next[action.name]
      setGroupStylesState(next)
      groupStylesRef.current = next
      persistLayout()
    }
    rawDispatch(action)
  }

  // Duplicate / copy / paste all plant a stamp under a fresh name, so they
  // share one path. The new node lands beside its source rather than on the
  // dagre spot an unplaced node would get — a copy you cannot see is a copy
  // you think failed.
  const PASTE_OFFSET = 48
  const plant = (stamp: NodeStamp, near: string | null) => {
    const device = stamp.node.device ?? state.doc.defaultDevice
    if (device === undefined) {
      toast.error('Paste needs a device: the copied node had none and the lab has no default')
      return
    }
    const name = nextNodeName(state.doc, device)
    const source = near !== null ? positionsRef.current[near] : undefined
    if (source !== undefined) {
      onPositions(
        { ...positionsRef.current, [name]: { x: source.x + PASTE_OFFSET, y: source.y + PASTE_OFFSET } },
        true,
      )
    }
    dispatch({ type: 'insert-node', name, stamp })
  }

  const duplicateNode = (name: string) => {
    const stamp = nodeStamp(state.doc, name)
    if (stamp !== null) plant(stamp, name)
  }

  const copySelectedNode = () => {
    if (state.selection.kind !== 'node') return
    const stamp = nodeStamp(state.doc, state.selection.name)
    if (stamp === null) return
    setClipboard(stamp)
    toast.success(`Copied ${state.selection.name}`)
  }

  const pasteNode = () => {
    if (clipboard === null) return
    plant(clipboard, state.selection.kind === 'node' ? state.selection.name : null)
  }

  // Editing shortcuts, bound at the window because the canvas is not the only
  // place a selection can be made (the inspector is outside it). Anything
  // typed into a field belongs to that field: text inputs have their own undo
  // stack and CodeMirror owns its keymap entirely.
  const shortcutsRef = useRef({ copySelectedNode, pasteNode })
  shortcutsRef.current = { copySelectedNode, pasteNode }
  useEffect(() => {
    if (mode !== 'visual') return
    const isTyping = (target: EventTarget | null): boolean =>
      target instanceof HTMLElement &&
      (target.isContentEditable ||
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement)
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return
      if (isTyping(event.target)) return
      const key = event.key.toLowerCase()
      if (key === 'z') {
        event.preventDefault()
        rawDispatch({ type: event.shiftKey ? 'redo' : 'undo' })
      } else if (key === 'y') {
        // Windows/Linux muscle memory for redo, alongside Ctrl+Shift+Z.
        event.preventDefault()
        rawDispatch({ type: 'redo' })
      } else if (key === 'c') {
        // Never steal a real text copy: with a selection on the page, Ctrl+C
        // means "copy that text", not "copy the selected node".
        if ((window.getSelection()?.toString() ?? '') !== '') return
        event.preventDefault()
        shortcutsRef.current.copySelectedNode()
      } else if (key === 'v') {
        event.preventDefault()
        shortcutsRef.current.pasteNode()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [mode])

  // Keep the builder in sync with server-side changes, but only while clean:
  // a dirty builder is last-write-wins (as the old edit dialog was) with an
  // explicit hint instead of a silent draft wipe.
  const [syncedDefinition, setSyncedDefinition] = useState(lab.definition)
  useEffect(() => {
    if (lab.definition === syncedDefinition || dirty) return
    setSyncedDefinition(lab.definition)
    const next =
      lab.definition === null
        ? ({ ok: true, doc: emptyBuildDoc(), notices: [] } as const)
        : parseBuildDoc(lab.definition, knownDevices)
    if (next.ok) rawDispatch({ type: 'reset', doc: next.doc })
  }, [lab.definition, syncedDefinition, dirty, knownDevices])
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
        const reparsed = parseBuildDoc(updated.definition, knownDevices)
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
      else toastError(err, 'Save failed')
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

  // The mode switch lives inside the workspace itself — a dedicated toolbar
  // row cost too much height. On the canvas it's one icon button among the
  // view tools; the text editor gets the two-way switch overlaid top-right.
  const textModeButton = (
    <Button
      variant="outline"
      size="icon-sm"
      title="Edit as text"
      aria-label="Edit the definition as text"
      onClick={() => requestMode('text')}
    >
      <FileCode2 className="size-3.5" />
    </Button>
  )
  const modeSwitch = (
    <Tabs value={mode} onValueChange={(value) => requestMode(value as Mode)}>
      <TabsList className="bg-card/90 backdrop-blur-sm">
        <TabsTrigger value="visual">Visual</TabsTrigger>
        <TabsTrigger value="text">Text</TabsTrigger>
      </TabsList>
    </Tabs>
  )

  return (
    <div className="flex flex-col gap-4">
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

      {mode === 'visual' && parsed.ok && parsed.notices.length > 0 && (
        <div className="rounded-[2px] border bg-card px-3 py-2 text-sm text-muted-foreground">
          <ul className="list-inside list-disc">
            {parsed.notices.map((notice) => (
              <li key={notice}>{notice}</li>
            ))}
          </ul>
        </div>
      )}

      {saveError !== null && (
        <div className="rounded-[2px] border border-destructive/50 bg-card px-3 py-2 text-sm">
          <div className="flex items-start justify-between gap-2">
            <p className="text-destructive">netlab rejected the definition: {saveError.message}</p>
            <Button
              variant="ghost"
              size="icon-xs"
              title="Dismiss"
              aria-label="Dismiss error"
              onClick={() => setSaveError(null)}
            >
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
              <div className="h-[max(20rem,calc(100vh-30rem))] rounded-[2px] border">
                <TopologyCanvas lab={lab} topology={preview} />
              </div>
            )}
          </CardContent>
        </Card>
      ) : mode === 'visual' ? (
        <div className="flex items-stretch gap-4">
          <Card className="min-w-0 flex-1 py-0">
            <CardContent className="p-0">
              <div className="h-[max(28rem,calc(100vh-20rem))]">
                <BuilderCanvas
                  state={state}
                  dispatch={dispatch}
                  labName={name}
                  positions={positions}
                  onPositions={onPositions}
                  groupStyles={groupStyles}
                  history={{
                    canUndo: canUndo(history),
                    canRedo: canRedo(history),
                    undo: () => rawDispatch({ type: 'undo' }),
                    redo: () => rawDispatch({ type: 'redo' }),
                  }}
                  onPasteNode={clipboard === null ? undefined : pasteNode}
                  topRight={textModeButton}
                />
              </div>
            </CardContent>
          </Card>
          <aside className="flex w-80 shrink-0 flex-col rounded-[2px] border bg-card">
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              <Inspector
                state={state}
                labName={name}
                dispatch={dispatch}
                groupStyles={groupStyles}
                onGroupColor={onGroupColor}
                onDuplicateNode={duplicateNode}
                onCopyNode={copySelectedNode}
              />
            </div>
            <div className="flex flex-col gap-2 border-t p-3">
              {serverChanged && (
                <p className="text-xs text-muted-foreground">
                  Definition changed on the server — saving overwrites it.
                </p>
              )}
              <div className="flex items-center justify-end gap-2">
                {state.dirty && (
                  <>
                    <span className="mr-auto font-mono text-xs text-muted-foreground">
                      unsaved changes
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={discardVisual}
                      disabled={save.isPending}
                    >
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
            </div>
          </aside>
        </div>
      ) : (
        <DefinitionEditor
          definition={lab.definition}
          saving={save.isPending}
          onSave={saveText}
          onDirtyChange={setTextDirty}
          corner={modeSwitch}
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
