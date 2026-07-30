import { Trash2, Unlink, X } from 'lucide-react'
import { useState, type Dispatch } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
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
import { Separator } from '@/components/ui/separator'
import {
  BUILDER_MODULES,
  NODE_NAME_MAX,
  NODE_NAME_RE,
  type BuildDoc,
  type BuildNode,
  type BuilderModule,
} from '@/lib/build-doc'
import { DEVICE_CATALOG, catalogDevice, deviceSupports } from '@/lib/device-catalog'

import type { BuilderAction, BuilderState } from './build-state'

// The builder's right-hand inspector: renders the form for whatever is
// selected (nothing → lab settings). Inputs are controlled directly against
// the BuildDoc and dispatch patches — the reducer is the only state.

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="font-mono text-[0.65rem] tracking-wide text-muted-foreground uppercase">
      {children}
    </h3>
  )
}

const nameError = (draft: string, doc: BuildDoc, current: string): string | null => {
  if (draft === current) return null
  if (draft.length === 0) return 'a name is required'
  if (draft.length > NODE_NAME_MAX) return `at most ${NODE_NAME_MAX} characters`
  if (!NODE_NAME_RE.test(draft)) {
    return 'lowercase letters, digits and underscores; no hyphens (they would break the a-b link form)'
  }
  if (doc.nodes.some((node) => node.name === draft)) return `"${draft}" is already taken`
  return null
}

const vrfNameError = (draft: string, doc: BuildDoc): string | null => {
  if (draft.length === 0) return null // nothing typed yet — no error, no add
  if (draft.length > NODE_NAME_MAX) return `at most ${NODE_NAME_MAX} characters`
  if (!NODE_NAME_RE.test(draft)) return 'lowercase letters, digits and underscores'
  if (doc.vrfs.includes(draft)) return `"${draft}" already exists`
  return null
}

function ModuleCheckboxes({
  idPrefix,
  selected,
  onToggle,
  isDisabled,
  disabledHint,
}: {
  idPrefix: string
  selected: readonly BuilderModule[]
  onToggle: (module: BuilderModule, checked: boolean) => void
  isDisabled?: (module: BuilderModule) => boolean
  disabledHint?: string
}) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-2">
      {BUILDER_MODULES.map((module) => {
        const id = `${idPrefix}-${module}`
        const disabled = isDisabled?.(module) ?? false
        return (
          <div key={module} className="flex items-center gap-2" title={disabled ? disabledHint : undefined}>
            <Checkbox
              id={id}
              disabled={disabled}
              checked={selected.includes(module)}
              onCheckedChange={(checked) => onToggle(module, checked === true)}
            />
            <Label htmlFor={id} className={disabled ? 'font-normal text-muted-foreground' : 'font-normal'}>
              {module}
            </Label>
          </div>
        )
      })}
    </div>
  )
}

function toggled(list: readonly BuilderModule[], module: BuilderModule, checked: boolean): BuilderModule[] {
  return checked ? [...new Set([...list, module])] : list.filter((entry) => entry !== module)
}

function LabInspector({ doc, dispatch }: { doc: BuildDoc; dispatch: Dispatch<BuilderAction> }) {
  const [vrfDraft, setVrfDraft] = useState('')
  const vrfError = vrfNameError(vrfDraft, doc)
  const memberCount = (vrf: string) =>
    doc.nodes.filter((node) => node.vrfs !== undefined && vrf in node.vrfs).length

  return (
    <div className="flex flex-col gap-4">
      <SectionTitle>lab settings</SectionTitle>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="build-default-device">Default device</Label>
        <Select
          value={doc.defaultDevice ?? 'none'}
          onValueChange={(value) =>
            dispatch({ type: 'patch-lab', patch: { defaultDevice: value === 'none' ? undefined : value } })
          }
        >
          <SelectTrigger id="build-default-device" size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">(none — every node picks its own)</SelectItem>
            {DEVICE_CATALOG.map((device) => (
              <SelectItem key={device.device} value={device.device}>
                {device.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>Global modules</Label>
        <ModuleCheckboxes
          idPrefix="build-lab-mod"
          selected={doc.modules}
          onToggle={(module, checked) =>
            dispatch({ type: 'patch-lab', patch: { modules: toggled(doc.modules, module, checked) } })
          }
        />
        <p className="text-xs text-muted-foreground">
          Nodes inherit these unless overridden per node.
        </p>
      </div>

      {doc.modules.includes('bgp') && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="build-bgp-as">BGP AS</Label>
          <Input
            id="build-bgp-as"
            type="number"
            className="h-8 font-mono"
            placeholder="65000"
            value={doc.bgpAs ?? ''}
            onChange={(event) => {
              const raw = event.target.value
              dispatch({
                type: 'patch-lab',
                patch: { bgpAs: raw === '' ? undefined : Number(raw) },
              })
            }}
          />
        </div>
      )}

      {doc.modules.includes('mpls') && (
        <div className="flex items-center gap-2">
          <Checkbox
            id="build-mpls-ldp"
            checked={doc.mplsLdp === true}
            onCheckedChange={(checked) =>
              dispatch({ type: 'patch-lab', patch: { mplsLdp: checked === true ? true : undefined } })
            }
          />
          <Label htmlFor="build-mpls-ldp" className="font-normal">
            LDP transport (mpls.ldp)
          </Label>
        </div>
      )}

      {doc.modules.includes('vrf') && (
        <div className="flex flex-col gap-1.5">
          <Label>VRFs</Label>
          {doc.vrfs.length === 0 && (
            <p className="text-xs text-muted-foreground">None yet — add one to place customer sites.</p>
          )}
          {doc.vrfs.map((vrf) => {
            const members = memberCount(vrf)
            const remove = () => dispatch({ type: 'remove-vrf', name: vrf })
            return (
              <div key={vrf} className="flex items-center justify-between gap-2 rounded-[2px] border px-2 py-1">
                <span className="font-mono text-sm">{vrf}</span>
                <span className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">
                    {members} member{members === 1 ? '' : 's'}
                  </span>
                  {members > 0 ? (
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="ghost" size="icon-xs" title={`Remove vrf ${vrf}`}>
                          <X className="size-3" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Remove vrf {vrf}?</AlertDialogTitle>
                          <AlertDialogDescription>
                            {members} node{members === 1 ? ' is' : 's are'} in this vrf — removing it
                            also removes those memberships.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction onClick={remove}>Remove</AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  ) : (
                    <Button variant="ghost" size="icon-xs" title={`Remove vrf ${vrf}`} onClick={remove}>
                      <X className="size-3" />
                    </Button>
                  )}
                </span>
              </div>
            )
          })}
          <div className="flex items-start gap-1.5">
            <div className="flex-1">
              <Input
                className="h-8 font-mono"
                placeholder="vrf name"
                value={vrfDraft}
                aria-invalid={vrfError !== null}
                onChange={(event) => setVrfDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && vrfDraft !== '' && vrfError === null) {
                    dispatch({ type: 'add-vrf', name: vrfDraft })
                    setVrfDraft('')
                  }
                }}
              />
              {vrfError !== null && <p className="mt-1 text-xs text-destructive">{vrfError}</p>}
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={vrfDraft === '' || vrfError !== null}
              onClick={() => {
                dispatch({ type: 'add-vrf', name: vrfDraft })
                setVrfDraft('')
              }}
            >
              Add
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function NodeInspector({
  doc,
  node,
  dispatch,
}: {
  doc: BuildDoc
  node: BuildNode
  dispatch: Dispatch<BuilderAction>
}) {
  const [nameDraft, setNameDraft] = useState(node.name)
  const draftError = nameError(nameDraft, doc, node.name)
  const commitName = () => {
    if (nameDraft !== node.name && draftError === null) {
      dispatch({ type: 'rename-node', from: node.name, to: nameDraft })
    }
  }

  const effectiveDevice = node.device ?? doc.defaultDevice
  const catalog = effectiveDevice !== undefined ? catalogDevice(effectiveDevice) : undefined
  const overridden = node.modules !== undefined
  const effectiveModules = node.modules ?? doc.modules
  const mplsVpnReady = (['mpls', 'bgp', 'vrf'] as const).every((m) => effectiveModules.includes(m))

  return (
    <div className="flex flex-col gap-4">
      <SectionTitle>node</SectionTitle>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="build-node-name">Name</Label>
        <Input
          id="build-node-name"
          className="h-8 font-mono"
          value={nameDraft}
          aria-invalid={draftError !== null}
          onChange={(event) => setNameDraft(event.target.value)}
          onBlur={commitName}
          onKeyDown={(event) => {
            if (event.key === 'Enter') commitName()
          }}
        />
        {draftError !== null && <p className="text-xs text-destructive">{draftError}</p>}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="build-node-device">Device</Label>
        <Select
          value={node.device ?? (doc.defaultDevice !== undefined ? 'inherit' : '')}
          onValueChange={(value) =>
            dispatch({
              type: 'patch-node',
              name: node.name,
              patch: { device: value === 'inherit' ? undefined : value },
            })
          }
        >
          <SelectTrigger id="build-node-device" size="sm">
            <SelectValue placeholder="pick a device" />
          </SelectTrigger>
          <SelectContent>
            {doc.defaultDevice !== undefined && (
              <SelectItem value="inherit">default ({doc.defaultDevice})</SelectItem>
            )}
            {DEVICE_CATALOG.map((device) => (
              <SelectItem key={device.device} value={device.device}>
                {device.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {effectiveDevice === undefined && (
          <p className="text-xs text-destructive">
            No device and no lab default — a device is required to save.
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <Label>Modules</Label>
          <Button
            variant="ghost"
            size="xs"
            onClick={() =>
              dispatch({
                type: 'patch-node',
                name: node.name,
                patch: {
                  modules: overridden
                    ? undefined
                    : doc.modules.filter(
                        (m) => effectiveDevice === undefined || deviceSupports(effectiveDevice, m),
                      ),
                },
              })
            }
          >
            {overridden ? 'Use global modules' : 'Override for this node'}
          </Button>
        </div>
        {overridden ? (
          <ModuleCheckboxes
            idPrefix={`build-node-mod-${node.name}`}
            selected={effectiveModules}
            onToggle={(module, checked) =>
              dispatch({
                type: 'patch-node',
                name: node.name,
                patch: { modules: toggled(effectiveModules, module, checked) },
              })
            }
            isDisabled={(module) =>
              effectiveDevice !== undefined && !deviceSupports(effectiveDevice, module)
            }
            disabledHint={
              catalog !== undefined ? `${catalog.label} does not support this module` : undefined
            }
          />
        ) : (
          <p className="text-xs text-muted-foreground">
            Inherits global modules
            {doc.modules.length > 0 ? ` (${doc.modules.join(', ')})` : ' (none set)'}.
          </p>
        )}
        {catalog?.kind === 'host' && (
          <p className="text-xs text-muted-foreground">
            {catalog.label} runs no routing modules — it joins links as a plain host.
          </p>
        )}
      </div>

      {effectiveModules.includes('bgp') && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="build-node-as">BGP AS (node)</Label>
          <Input
            id="build-node-as"
            type="number"
            className="h-8 font-mono"
            placeholder={doc.bgpAs !== undefined ? `${doc.bgpAs} (lab)` : 'unset'}
            value={node.bgpAs ?? ''}
            onChange={(event) => {
              const raw = event.target.value
              dispatch({
                type: 'patch-node',
                name: node.name,
                patch: { bgpAs: raw === '' ? undefined : Number(raw) },
              })
            }}
          />
        </div>
      )}

      <div className="flex items-center gap-2" title={mplsVpnReady ? undefined : 'needs mpls, bgp and vrf modules on this node'}>
        <Checkbox
          id="build-node-vpn"
          disabled={!mplsVpnReady}
          checked={node.mplsVpn === true}
          onCheckedChange={(checked) =>
            dispatch({
              type: 'patch-node',
              name: node.name,
              patch: { mplsVpn: checked === true ? true : undefined },
            })
          }
        />
        <Label
          htmlFor="build-node-vpn"
          className={mplsVpnReady ? 'font-normal' : 'font-normal text-muted-foreground'}
        >
          MPLS VPN edge (mpls.vpn)
        </Label>
      </div>

      {doc.vrfs.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <Label>VRF membership</Label>
          {doc.vrfs.map((vrf) => {
            const membership = node.vrfs?.[vrf]
            const member = membership !== undefined
            const id = `build-node-vrf-${vrf}`
            const setVrfs = (next: Record<string, { loopback?: boolean }>) =>
              dispatch({
                type: 'patch-node',
                name: node.name,
                patch: { vrfs: Object.keys(next).length > 0 ? next : undefined },
              })
            return (
              <div key={vrf} className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <Checkbox
                    id={id}
                    checked={member}
                    onCheckedChange={(checked) => {
                      const next = { ...node.vrfs }
                      if (checked === true) next[vrf] = {}
                      else delete next[vrf]
                      setVrfs(next)
                    }}
                  />
                  <Label htmlFor={id} className="font-mono font-normal">
                    {vrf}
                  </Label>
                </div>
                {member && (
                  <div className="ml-6 flex items-center gap-2">
                    <Checkbox
                      id={`${id}-loopback`}
                      checked={membership.loopback === true}
                      onCheckedChange={(checked) =>
                        setVrfs({
                          ...node.vrfs,
                          [vrf]: checked === true ? { loopback: true } : {},
                        })
                      }
                    />
                    <Label htmlFor={`${id}-loopback`} className="text-xs font-normal text-muted-foreground">
                      customer loopback (the site)
                    </Label>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      <details>
        <summary className="cursor-pointer text-xs text-muted-foreground select-none">Advanced</summary>
        <div className="mt-2 flex flex-col gap-1.5">
          <Label htmlFor="build-node-image">Image override</Label>
          <Input
            id="build-node-image"
            className="h-8 font-mono"
            placeholder="netlab default for the device"
            value={node.image ?? ''}
            onChange={(event) => {
              const raw = event.target.value
              dispatch({
                type: 'patch-node',
                name: node.name,
                patch: { image: raw === '' ? undefined : raw },
              })
            }}
          />
        </div>
      </details>

      <Separator />
      <Button
        variant="outline"
        size="sm"
        className="justify-start gap-2 text-destructive"
        onClick={() => dispatch({ type: 'delete-node', name: node.name })}
      >
        <Trash2 className="size-3.5" />
        Delete node (removes its links)
      </Button>
    </div>
  )
}

/** The builder's right-hand inspector, dispatching on the selection. */
export function Inspector({
  state,
  dispatch,
}: {
  state: BuilderState
  dispatch: Dispatch<BuilderAction>
}) {
  const { doc, selection } = state

  switch (selection.kind) {
    case 'lab':
      return <LabInspector doc={doc} dispatch={dispatch} />
    case 'node': {
      const node = doc.nodes.find((entry) => entry.name === selection.name)
      if (node === undefined) return <LabInspector doc={doc} dispatch={dispatch} />
      // Keyed remount resets the name draft when the selection moves.
      return <NodeInspector key={node.name} doc={doc} node={node} dispatch={dispatch} />
    }
    case 'link': {
      const link = doc.links[selection.linkIndex]
      if (link === undefined || link.kind !== 'p2p') return <LabInspector doc={doc} dispatch={dispatch} />
      return (
        <div className="flex flex-col gap-4">
          <SectionTitle>link</SectionTitle>
          <p className="font-mono text-sm">
            {link.a} ↔ {link.b}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="justify-start gap-2 text-destructive"
            onClick={() => dispatch({ type: 'delete-link', linkIndex: selection.linkIndex })}
          >
            <Unlink className="size-3.5" />
            Delete link
          </Button>
        </div>
      )
    }
    case 'lan': {
      const link = doc.links[selection.linkIndex]
      if (link === undefined || link.kind !== 'lan') return <LabInspector doc={doc} dispatch={dispatch} />
      return (
        <div className="flex flex-col gap-4">
          <SectionTitle>lan segment</SectionTitle>
          {link.members.length === 0 && (
            <p className="text-xs text-muted-foreground">
              No members yet — drag from a node onto this segment.
            </p>
          )}
          {link.members.map((member) => (
            <div key={member} className="flex items-center justify-between gap-2 rounded-[2px] border px-2 py-1">
              <span className="font-mono text-sm">{member}</span>
              <Button
                variant="ghost"
                size="icon-xs"
                title={`Remove ${member} from the segment`}
                onClick={() =>
                  dispatch({ type: 'remove-member', linkIndex: selection.linkIndex, node: member })
                }
              >
                <X className="size-3" />
              </Button>
            </div>
          ))}
          {link.members.length > 0 && link.members.length < 3 && (
            <p className="text-xs text-destructive">
              A LAN needs at least three members to save
              {link.members.length === 2 ? ' — for two, use a direct link' : ''}.
            </p>
          )}
          <Button
            variant="outline"
            size="sm"
            className="justify-start gap-2 text-destructive"
            onClick={() => dispatch({ type: 'delete-link', linkIndex: selection.linkIndex })}
          >
            <Trash2 className="size-3.5" />
            Delete segment
          </Button>
        </div>
      )
    }
    case 'member': {
      const link = doc.links[selection.linkIndex]
      if (link === undefined || link.kind !== 'lan') return <LabInspector doc={doc} dispatch={dispatch} />
      return (
        <div className="flex flex-col gap-4">
          <SectionTitle>lan membership</SectionTitle>
          <p className="font-mono text-sm">
            {selection.node} on {link.id}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="justify-start gap-2 text-destructive"
            onClick={() =>
              dispatch({ type: 'remove-member', linkIndex: selection.linkIndex, node: selection.node })
            }
          >
            <Unlink className="size-3.5" />
            Remove from segment
          </Button>
        </div>
      )
    }
  }
}
