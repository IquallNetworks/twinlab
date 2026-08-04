import { useQuery } from '@tanstack/react-query'
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
  declaredVrfs,
  extrasOwn,
  groupExtrasKeyError,
  labExtrasKeyError,
  nodeExtrasKeyError,
  type BuildDoc,
  type BuildGroup,
  type BuildNode,
  type BuilderModule,
} from '@/lib/build-doc'
import { catalogDevice, deviceSupports } from '@/lib/device-catalog'
import { GROUP_PALETTE, groupColor, type GroupStyles } from '@/lib/group-colors'
import { customConfigQueryOptions } from '@/lib/queries'
import { useDeviceCatalog } from '@/lib/use-device-catalog'
import { cn } from '@/lib/utils'

import type { BuilderAction, BuilderState } from './build-state'
import { ExtrasEditor } from './extras-editor'

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

const groupNameError = (draft: string, doc: BuildDoc, current?: string): string | null => {
  if (draft === current) return null
  if (draft.length === 0) return 'a name is required'
  if (draft.length > NODE_NAME_MAX) return `at most ${NODE_NAME_MAX} characters`
  if (!NODE_NAME_RE.test(draft)) return 'lowercase letters, digits and underscores'
  if (doc.groups.some((group) => group.name === draft)) return `"${draft}" already exists`
  return null
}

function GroupBlock({
  doc,
  group,
  knownTemplates,
  groupStyles,
  onGroupColor,
  dispatch,
}: {
  doc: BuildDoc
  group: BuildGroup
  knownTemplates: readonly string[]
  groupStyles: GroupStyles
  onGroupColor: (group: string, color: string) => void
  dispatch: Dispatch<BuilderAction>
}) {
  const color = groupColor(groupStyles, group.name)
  const [nameDraft, setNameDraft] = useState(group.name)
  const draftError = groupNameError(nameDraft, doc, group.name)
  const commitName = () => {
    if (nameDraft !== group.name && draftError === null) {
      dispatch({ type: 'rename-group', from: group.name, to: nameDraft })
    }
  }
  const setConfig = (next: string[]) =>
    dispatch({
      type: 'patch-group',
      name: group.name,
      patch: { config: next.length > 0 ? next : undefined },
    })
  const config = group.config ?? []
  // A stored group may reference templates this lab doesn't carry — keep them
  // visible and removable rather than dropping them from the picker.
  const unknownConfig = config.filter((entry) => !knownTemplates.includes(entry))

  return (
    <div className="flex flex-col gap-2 rounded-[2px] border p-2">
      <div className="flex items-start gap-1.5">
        <span
          aria-hidden="true"
          className="mt-2.5 size-2.5 shrink-0 rounded-full border border-background"
          style={{ backgroundColor: color }}
        />
        <div className="flex-1">
          <Input
            className="h-8 font-mono"
            aria-label={`Group ${group.name} name`}
            value={nameDraft}
            aria-invalid={draftError !== null}
            onChange={(event) => setNameDraft(event.target.value)}
            onBlur={commitName}
            onKeyDown={(event) => {
              if (event.key === 'Enter') commitName()
            }}
          />
          {draftError !== null && <p className="mt-1 text-xs text-destructive">{draftError}</p>}
        </div>
        <Button
          variant="ghost"
          size="icon-xs"
          title={`Delete group ${group.name}`}
          onClick={() => dispatch({ type: 'delete-group', name: group.name })}
        >
          <Trash2 className="size-3" />
        </Button>
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">Members</span>
        {doc.nodes.length === 0 ? (
          <p className="text-xs text-muted-foreground">No nodes yet.</p>
        ) : (
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {doc.nodes.map((node) => {
              const id = `build-group-${group.name}-member-${node.name}`
              const member = group.members.includes(node.name)
              return (
                <div key={node.name} className="flex items-center gap-1.5">
                  <Checkbox
                    id={id}
                    checked={member}
                    onCheckedChange={(checked) =>
                      dispatch({
                        type: 'patch-group',
                        name: group.name,
                        patch: {
                          members:
                            checked === true
                              ? [...group.members, node.name]
                              : group.members.filter((entry) => entry !== node.name),
                        },
                      })
                    }
                  />
                  <Label htmlFor={id} className="font-mono text-xs font-normal">
                    {node.name}
                  </Label>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">Config templates</span>
        {knownTemplates.length === 0 && unknownConfig.length === 0 ? (
          <p className="text-xs text-muted-foreground">No templates available.</p>
        ) : (
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {knownTemplates.map((template) => {
              const id = `build-group-${group.name}-config-${template}`
              return (
                <div key={template} className="flex items-center gap-1.5">
                  <Checkbox
                    id={id}
                    checked={config.includes(template)}
                    onCheckedChange={(checked) =>
                      setConfig(
                        checked === true
                          ? [...config, template]
                          : config.filter((entry) => entry !== template),
                      )
                    }
                  />
                  <Label htmlFor={id} className="font-mono text-xs font-normal">
                    {template}
                  </Label>
                </div>
              )
            })}
            {unknownConfig.map((entry) => (
              <span
                key={entry}
                className="flex items-center gap-1 rounded-[2px] border px-1.5 py-0.5 font-mono text-xs"
                title="Not among this lab's templates — kept as stored"
              >
                {entry}
                <Button
                  variant="ghost"
                  size="icon-xs"
                  title={`Remove ${entry}`}
                  onClick={() => setConfig(config.filter((item) => item !== entry))}
                >
                  <X className="size-3" />
                </Button>
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">Color</span>
        <div className="flex flex-wrap items-center gap-1.5">
          {GROUP_PALETTE.map((swatch) => (
            <button
              key={swatch}
              type="button"
              title={swatch}
              aria-label={`Color ${swatch}`}
              onClick={() => onGroupColor(group.name, swatch)}
              className={cn(
                'size-4 rounded-full border border-background',
                color.toLowerCase() === swatch && 'ring-2 ring-primary',
              )}
              style={{ backgroundColor: swatch }}
            />
          ))}
          <input
            type="color"
            aria-label={`Custom color for group ${group.name}`}
            title="Custom color"
            value={color}
            onChange={(event) => onGroupColor(group.name, event.target.value)}
            className="size-5 cursor-pointer rounded-[2px] border bg-transparent p-0"
          />
        </div>
      </div>

      <ExtrasEditor
        key={JSON.stringify(group.extras ?? {})}
        idPrefix={`build-group-${group.name}`}
        value={group.extras}
        keyError={groupExtrasKeyError}
        onApply={(extras) =>
          dispatch({ type: 'patch-group', name: group.name, patch: { extras } })
        }
      />
    </div>
  )
}

function GroupsSection({
  doc,
  labName,
  groupStyles,
  onGroupColor,
  dispatch,
}: {
  doc: BuildDoc
  labName: string
  groupStyles: GroupStyles
  onGroupColor: (group: string, color: string) => void
  dispatch: Dispatch<BuilderAction>
}) {
  const templates = useQuery(customConfigQueryOptions(labName))
  const knownTemplates = [
    ...(templates.data?.builtin.map((template) => template.name) ?? []),
    ...Object.keys(templates.data?.custom_config ?? {}).map((path) => path.replace(/\.j2$/, '')),
  ]
  const [draft, setDraft] = useState('')
  const draftError = draft === '' ? null : groupNameError(draft, doc)
  const add = () => {
    if (draft !== '' && draftError === null) {
      dispatch({ type: 'add-group', name: draft })
      setDraft('')
    }
  }

  if (extrasOwn(doc.extras, 'groups')) {
    return (
      <div className="flex flex-col gap-1.5">
        <Label>Groups</Label>
        <p className="text-xs text-muted-foreground">
          The groups block uses a form the controls can&apos;t edit — managed in Advanced
          properties.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1.5">
      <Label>Groups</Label>
      {doc.groups.length === 0 && (
        <p className="text-xs text-muted-foreground">
          None yet — a group broadcasts config templates and other properties to its members.
        </p>
      )}
      {doc.groups.map((group) => (
        <GroupBlock
          key={group.name}
          doc={doc}
          group={group}
          knownTemplates={knownTemplates}
          groupStyles={groupStyles}
          onGroupColor={onGroupColor}
          dispatch={dispatch}
        />
      ))}
      <div className="flex items-start gap-1.5">
        <div className="flex-1">
          <Input
            className="h-8 font-mono"
            placeholder="group name"
            value={draft}
            aria-invalid={draftError !== null}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') add()
            }}
          />
          {draftError !== null && <p className="mt-1 text-xs text-destructive">{draftError}</p>}
        </div>
        <Button variant="outline" size="sm" disabled={draft === '' || draftError !== null} onClick={add}>
          Add
        </Button>
      </div>
    </div>
  )
}

function LabInspector({
  doc,
  labName,
  groupStyles,
  onGroupColor,
  dispatch,
}: {
  doc: BuildDoc
  labName: string
  groupStyles: GroupStyles
  onGroupColor: (group: string, color: string) => void
  dispatch: Dispatch<BuilderAction>
}) {
  const { devices } = useDeviceCatalog()
  const [vrfDraft, setVrfDraft] = useState('')
  const vrfError = vrfNameError(vrfDraft, doc)
  const memberCount = (vrf: string) =>
    doc.nodes.filter((node) => node.vrfs !== undefined && vrf in node.vrfs).length
  const modulesOwned = extrasOwn(doc.extras, 'module')
  const vrfsOwned = extrasOwn(doc.extras, 'vrfs')

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
            {devices.map((device) => (
              <SelectItem key={device.device} value={device.device}>
                {device.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>Global modules</Label>
        {modulesOwned ? (
          <p className="text-xs text-muted-foreground">
            The module list carries entries outside the builder&apos;s set — managed in Advanced
            properties.
          </p>
        ) : (
          <>
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
          </>
        )}
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

      {vrfsOwned && (
        <div className="flex flex-col gap-1.5">
          <Label>VRFs</Label>
          <p className="text-xs text-muted-foreground">
            The vrfs carry attributes (rd, rt, …) the controls can&apos;t edit — managed in
            Advanced properties.
          </p>
        </div>
      )}
      {!vrfsOwned && doc.modules.includes('vrf') && (
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

      <GroupsSection
        doc={doc}
        labName={labName}
        groupStyles={groupStyles}
        onGroupColor={onGroupColor}
        dispatch={dispatch}
      />

      <ExtrasEditor
        key={JSON.stringify(doc.extras)}
        idPrefix="build-lab"
        value={doc.extras}
        keyError={labExtrasKeyError}
        onApply={(extras) => dispatch({ type: 'patch-lab', patch: { extras: extras ?? {} } })}
      />
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
  const { devices } = useDeviceCatalog()
  const [nameDraft, setNameDraft] = useState(node.name)
  const draftError = nameError(nameDraft, doc, node.name)
  const commitName = () => {
    if (nameDraft !== node.name && draftError === null) {
      dispatch({ type: 'rename-node', from: node.name, to: nameDraft })
    }
  }

  const effectiveDevice = node.device ?? doc.defaultDevice
  const catalog = effectiveDevice !== undefined ? catalogDevice(devices, effectiveDevice) : undefined
  const overridden = node.modules !== undefined
  const effectiveModules = node.modules ?? doc.modules
  const mplsVpnReady = (['mpls', 'bgp', 'vrf'] as const).every((m) => effectiveModules.includes(m))
  const modulesOwned = extrasOwn(node.extras, 'module')
  const vrfsOwned = extrasOwn(node.extras, 'vrfs')
  const vrfNames = declaredVrfs(doc)

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
            {devices.map((device) => (
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
        {catalog !== undefined && catalog.imagePresent === false && (
          <p className="text-xs text-muted-foreground">
            {catalog.label}&apos;s default image is not present on the host — deploy will try to
            pull it.
          </p>
        )}
      </div>

      {modulesOwned ? (
        <div className="flex flex-col gap-1.5">
          <Label>Modules</Label>
          <p className="text-xs text-muted-foreground">
            The module list carries entries outside the builder&apos;s set — managed in Advanced
            properties.
          </p>
        </div>
      ) : (
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
                        (m) => effectiveDevice === undefined || deviceSupports(devices, effectiveDevice, m),
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
              effectiveDevice !== undefined && !deviceSupports(devices, effectiveDevice, module)
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
      )}

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

      {vrfsOwned && (
        <div className="flex flex-col gap-1.5">
          <Label>VRF membership</Label>
          <p className="text-xs text-muted-foreground">
            This node&apos;s vrfs use a form the controls can&apos;t edit — managed in Advanced
            properties.
          </p>
        </div>
      )}
      {!vrfsOwned && vrfNames.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <Label>VRF membership</Label>
          {vrfNames.map((vrf) => {
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

      {doc.groups.length > 0 && !extrasOwn(doc.extras, 'groups') && (
        <div className="flex flex-col gap-1.5">
          <Label>Groups</Label>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {doc.groups.map((group) => {
              const id = `build-node-group-${group.name}`
              const member = group.members.includes(node.name)
              return (
                <div key={group.name} className="flex items-center gap-1.5">
                  <Checkbox
                    id={id}
                    checked={member}
                    onCheckedChange={(checked) =>
                      dispatch({
                        type: 'patch-group',
                        name: group.name,
                        patch: {
                          members:
                            checked === true
                              ? [...group.members, node.name]
                              : group.members.filter((entry) => entry !== node.name),
                        },
                      })
                    }
                  />
                  <Label htmlFor={id} className="font-mono text-xs font-normal">
                    {group.name}
                  </Label>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <details>
        <summary className="cursor-pointer text-xs text-muted-foreground select-none">Advanced</summary>
        <div className="mt-2 flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
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
          <ExtrasEditor
            key={JSON.stringify(node.extras ?? {})}
            idPrefix={`build-node-${node.name}`}
            value={node.extras}
            keyError={nodeExtrasKeyError}
            onApply={(extras) =>
              dispatch({ type: 'patch-node', name: node.name, patch: { extras } })
            }
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

/** The builder's right-hand inspector, dispatching on the selection.
 * `labName` feeds the groups section's template picker (custom-config query);
 * `groupStyles`/`onGroupColor` are the shared group colors (delta 20), owned
 * by the Build tab beside the positions. */
export function Inspector({
  state,
  labName,
  groupStyles,
  onGroupColor,
  dispatch,
}: {
  state: BuilderState
  labName: string
  groupStyles: GroupStyles
  onGroupColor: (group: string, color: string) => void
  dispatch: Dispatch<BuilderAction>
}) {
  const { doc, selection } = state
  const lab = (
    <LabInspector
      doc={doc}
      labName={labName}
      groupStyles={groupStyles}
      onGroupColor={onGroupColor}
      dispatch={dispatch}
    />
  )

  switch (selection.kind) {
    case 'lab':
      return lab
    case 'node': {
      const node = doc.nodes.find((entry) => entry.name === selection.name)
      if (node === undefined) return lab
      // Keyed remount resets the name draft when the selection moves.
      return <NodeInspector key={node.name} doc={doc} node={node} dispatch={dispatch} />
    }
    case 'link': {
      const link = doc.links[selection.linkIndex]
      if (link === undefined || link.kind !== 'p2p') return lab
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
      if (link === undefined || link.kind !== 'lan') return lab
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
      if (link === undefined || link.kind !== 'lan') return lab
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
