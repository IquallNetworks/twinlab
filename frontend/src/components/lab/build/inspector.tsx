import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bookmark,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Copy,
  CopyPlus,
  Trash2,
  Unlink,
  Waypoints,
  X,
} from 'lucide-react'
import { useState, type Dispatch } from 'react'
import { toast } from 'sonner'

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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  NODE_NAME_MAX,
  NODE_ROLES,
  NODE_NAME_RE,
  declaredVrfs,
  emitNodeFragment,
  extrasOwn,
  groupExtrasKeyError,
  labExtrasKeyError,
  declaredNodes,
  linkExtrasKeyError,
  nextStubId,
  nodeExtrasKeyError,
  type BuildDoc,
  type BuildGroup,
  type BuildLink,
  type BuildNode,
  type BuildNodeLoopback,
  type BuildNodeVrf,
  type BuilderModule,
  type NodeRole,
  type LinkAttrs,
  type LinkEndpoint,
} from '@/lib/build-doc'
import { api } from '@/lib/api'
import { catalogDevice, deviceSupports, offeredModules } from '@/lib/device-catalog'
import { toastError } from '@/lib/error-toast'
import { GROUP_PALETTE, groupColor, type GroupStyles } from '@/lib/group-colors'
import { customConfigQueryOptions, meQueryOptions, nodeTemplatesQueryOptions } from '@/lib/queries'
import type { ConfigTemplate } from '@/lib/schemas'
import { useDeviceCatalog } from '@/lib/use-device-catalog'
import { cn } from '@/lib/utils'

import { validateConnect, type BuilderAction, type BuilderState, type EndpointPatch } from './build-state'
import { DevicePicker } from './device-picker'
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

// Inspector tab plumbing: triggers are compact (the panel is w-80) and carry
// a count so populated tabs are visible without a click; content stays
// force-mounted so un-applied editor drafts survive a tab switch.
function InspectorTab({ value, children }: { value: string; children: React.ReactNode }) {
  return (
    <TabsTrigger className="min-w-0 px-1.5 text-xs" value={value}>
      {children}
    </TabsTrigger>
  )
}

function InspectorTabContent({
  value,
  children,
}: {
  value: string
  children: React.ReactNode
}) {
  return (
    <TabsContent
      forceMount
      value={value}
      className="flex flex-col gap-4 pt-1 data-[state=inactive]:hidden"
    >
      {children}
    </TabsContent>
  )
}

const countSuffix = (count: number): string => (count > 0 ? ` (${count})` : '')

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
  if (doc.vrfs.some((vrf) => vrf.name === draft)) return `"${draft}" already exists`
  return null
}

function ModuleCheckboxes({
  idPrefix,
  offered,
  selected,
  onToggle,
  isDisabled,
  disabledHint,
}: {
  idPrefix: string
  // The vocabulary is netlab's whole module set; only what some cataloged
  // device can run (plus what this document already selects) is offered.
  offered: readonly BuilderModule[]
  selected: readonly BuilderModule[]
  onToggle: (module: BuilderModule, checked: boolean) => void
  isDisabled?: (module: BuilderModule) => boolean
  disabledHint?: string
}) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-2">
      {offered.map((module) => {
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

/** One picker entry: a template name plus whether it applies to the current
 * target — delta 27's applicability rule: a variant matches by node name,
 * else by (effective) device, else universally; a group applies only when
 * every member is covered. Templates that don't apply are offered greyed
 * with the reason (the module-greying pattern), never hidden — attaching one
 * would fail the save's dry `netlab create` in netlab's voice. */
interface TemplateOffer {
  name: string
  applies: boolean
  reason?: string
}

/** A node's device as netlab resolves it: its own, else the lab default.
 * Undefined for an undeclared name (an `_auto_create` member) or a
 * device-less `include:` node — only node-scoped or universal variants can
 * match those. */
const effectiveDevice = (doc: BuildDoc, nodeName: string): string | undefined => {
  const node = doc.nodes.find((entry) => entry.name === nodeName)
  return node === undefined ? undefined : (node.device ?? doc.defaultDevice)
}

const variantMatches = (
  template: ConfigTemplate,
  nodeName: string,
  device: string | undefined,
): boolean =>
  template.variants.some(
    (variant) =>
      variant.node === nodeName ||
      (device !== undefined && variant.device === device) ||
      (variant.node == null && variant.device == null),
  )

function nodeTemplateOffers(
  templates: readonly ConfigTemplate[],
  doc: BuildDoc,
  nodeName: string,
): TemplateOffer[] {
  const device = effectiveDevice(doc, nodeName)
  return templates.map((template) => {
    if (variantMatches(template, nodeName, device)) return { name: template.name, applies: true }
    return {
      name: template.name,
      applies: false,
      reason: `No variant for ${device ?? 'this node'} — attaching it would fail the save`,
    }
  })
}

/** The group's node members, nested groups resolved transitively (netlab
 * groups nest); cycle-safe. */
function groupMemberNodes(doc: BuildDoc, group: BuildGroup): string[] {
  const members: string[] = []
  const seen = new Set<string>()
  const visit = (current: BuildGroup) => {
    if (seen.has(current.name)) return
    seen.add(current.name)
    for (const member of current.members) {
      const nested = doc.groups.find((entry) => entry.name === member)
      if (nested !== undefined) visit(nested)
      else members.push(member)
    }
  }
  visit(group)
  return members
}

function groupTemplateOffers(
  templates: readonly ConfigTemplate[],
  doc: BuildDoc,
  group: BuildGroup,
): TemplateOffer[] {
  const members = groupMemberNodes(doc, group)
  return templates.map((template) => {
    const failing = members.find(
      (member) => !variantMatches(template, member, effectiveDevice(doc, member)),
    )
    if (failing === undefined) return { name: template.name, applies: true }
    const device = effectiveDevice(doc, failing)
    return {
      name: template.name,
      applies: false,
      reason: `No variant for member ${failing}${device !== undefined ? ` (${device})` : ''} — a group attaches to every member`,
    }
  })
}

/** netlab's `config: [...]` — the custom-config templates attached to a
 * group's members or to one node. Shared by both, so the two spellings of the
 * same netlab key are edited the same way. */
function ConfigTemplatePicker({
  idPrefix,
  offers,
  config,
  onChange,
}: {
  idPrefix: string
  offers: readonly TemplateOffer[]
  config: readonly string[]
  onChange: (next: string[]) => void
}) {
  // A stored document may reference templates this lab doesn't carry — keep
  // them visible and removable rather than dropping them from the picker.
  const unknown = config.filter((entry) => !offers.some((offer) => offer.name === entry))
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">Config templates</span>
      {offers.length === 0 && unknown.length === 0 ? (
        <p className="text-xs text-muted-foreground">No templates available.</p>
      ) : (
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {offers.map((offer) => {
            const id = `${idPrefix}-config-${offer.name}`
            const checked = config.includes(offer.name)
            return (
              <div
                key={offer.name}
                className="flex items-center gap-1.5"
                title={offer.applies ? undefined : offer.reason}
              >
                <Checkbox
                  id={id}
                  checked={checked}
                  // A stored doc may already attach a non-applicable template
                  // — keep it uncheckable so the user can remove it.
                  disabled={!offer.applies && !checked}
                  onCheckedChange={(next) =>
                    onChange(
                      next === true
                        ? [...config, offer.name]
                        : config.filter((entry) => entry !== offer.name),
                    )
                  }
                />
                <Label
                  htmlFor={id}
                  className={
                    offer.applies
                      ? 'font-mono text-xs font-normal'
                      : 'font-mono text-xs font-normal text-muted-foreground'
                  }
                >
                  {offer.name}
                </Label>
              </div>
            )
          })}
          {unknown.map((entry) => (
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
                onClick={() => onChange(config.filter((item) => item !== entry))}
              >
                <X className="size-3" />
              </Button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function GroupColorDot({
  group,
  color,
  onGroupColor,
}: {
  group: string
  color: string
  onGroupColor: (group: string, color: string) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          title="Group color"
          aria-label={`Color for group ${group}`}
          className="size-4 shrink-0 cursor-pointer rounded-full border border-background"
          style={{ backgroundColor: color }}
        />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="flex w-auto items-center gap-1.5 p-2">
        {GROUP_PALETTE.map((swatch) => (
          <button
            key={swatch}
            type="button"
            title={swatch}
            aria-label={`Color ${swatch}`}
            onClick={() => {
              onGroupColor(group, swatch)
              setOpen(false)
            }}
            className={cn(
              'size-4 rounded-full border border-background',
              color.toLowerCase() === swatch && 'ring-2 ring-primary',
            )}
            style={{ backgroundColor: swatch }}
          />
        ))}
        <input
          type="color"
          aria-label={`Custom color for group ${group}`}
          title="Custom color"
          value={color}
          onChange={(event) => onGroupColor(group, event.target.value)}
          className="size-5 cursor-pointer rounded-[2px] border bg-transparent p-0"
        />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function GroupBlock({
  doc,
  group,
  templates,
  groupStyles,
  onGroupColor,
  expanded,
  onToggleExpanded,
  onRenamed,
  dispatch,
}: {
  doc: BuildDoc
  group: BuildGroup
  templates: readonly ConfigTemplate[]
  groupStyles: GroupStyles
  onGroupColor: (group: string, color: string) => void
  expanded: boolean
  onToggleExpanded: () => void
  // Keeps the section's expanded-group tracking on the new name after a rename.
  onRenamed: (to: string) => void
  dispatch: Dispatch<BuilderAction>
}) {
  const color = groupColor(groupStyles, group.name)
  const [nameDraft, setNameDraft] = useState(group.name)
  const draftError = groupNameError(nameDraft, doc, group.name)
  const commitName = () => {
    if (nameDraft !== group.name && draftError === null) {
      dispatch({ type: 'rename-group', from: group.name, to: nameDraft })
      onRenamed(nameDraft)
    }
  }

  if (!expanded) {
    return (
      <button
        type="button"
        aria-expanded={false}
        onClick={onToggleExpanded}
        className="flex items-center gap-2 rounded-[2px] border px-2 py-1.5 text-left hover:bg-accent/50"
      >
        <span
          aria-hidden="true"
          className="size-2.5 shrink-0 rounded-full border border-background"
          style={{ backgroundColor: color }}
        />
        <span className="flex-1 font-mono text-sm">{group.name}</span>
        <span className="text-xs text-muted-foreground">
          {group.members.length} member{group.members.length === 1 ? '' : 's'}
        </span>
        <ChevronRight className="size-3.5 text-muted-foreground" aria-hidden="true" />
      </button>
    )
  }
  const setConfig = (next: string[]) =>
    dispatch({
      type: 'patch-group',
      name: group.name,
      patch: { config: next.length > 0 ? next : undefined },
    })
  const config = group.config ?? []

  return (
    <div className="flex flex-col gap-2 rounded-[2px] border p-2">
      <div className="flex items-start gap-1.5">
        <span className="mt-2 flex shrink-0">
          <GroupColorDot group={group.name} color={color} onGroupColor={onGroupColor} />
        </span>
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
        <Button
          variant="ghost"
          size="icon-xs"
          aria-expanded={true}
          title={`Collapse group ${group.name}`}
          onClick={onToggleExpanded}
        >
          <ChevronDown className="size-3" />
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

      {/* netlab groups nest — a member may be another group, which then
          broadcasts this group's data to ITS members. */}
      {doc.groups.length > 1 && (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Member groups</span>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {doc.groups
              .filter((entry) => entry.name !== group.name)
              .map((entry) => {
                const id = `build-group-${group.name}-subgroup-${entry.name}`
                const member = group.members.includes(entry.name)
                return (
                  <div key={entry.name} className="flex items-center gap-1.5">
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
                                ? [...group.members, entry.name]
                                : group.members.filter((name) => name !== entry.name),
                          },
                        })
                      }
                    />
                    <Label htmlFor={id} className="font-mono text-xs font-normal">
                      {entry.name}
                    </Label>
                  </div>
                )
              })}
          </div>
        </div>
      )}

      <ConfigTemplatePicker
        idPrefix={`build-group-${group.name}`}
        offers={groupTemplateOffers(templates, doc, group)}
        config={config}
        onChange={setConfig}
      />

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
  const templateRecords = templates.data?.templates ?? []
  const [draft, setDraft] = useState('')
  // One group edits at a time — the rest collapse to summary rows.
  const [expanded, setExpanded] = useState<string | null>(null)
  const draftError = draft === '' ? null : groupNameError(draft, doc)
  const add = () => {
    if (draft !== '' && draftError === null) {
      dispatch({ type: 'add-group', name: draft })
      setExpanded(draft)
      setDraft('')
    }
  }

  if (extrasOwn(doc.extras, 'groups')) {
    return (
      <p className="text-xs text-muted-foreground">
        The groups block uses a form the controls can&apos;t edit — managed in Advanced
        properties.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-1.5">
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
          templates={templateRecords}
          groupStyles={groupStyles}
          onGroupColor={onGroupColor}
          expanded={expanded === group.name}
          onToggleExpanded={() => setExpanded(expanded === group.name ? null : group.name)}
          onRenamed={(to) => setExpanded(to)}
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
      {/* Settings that sit BESIDE the groups rather than being one (netlab
          reads a groups-level `_auto_create`). Only shown where they exist —
          they are rare, and there is nothing to teach when there are none. */}
      {doc.groupsExtras !== undefined && (
        <ExtrasEditor
          key={JSON.stringify(doc.groupsExtras)}
          idPrefix="build-groups-extras"
          label="groups-level settings"
          value={doc.groupsExtras}
          keyError={(_key, value) =>
            value !== null && typeof value === 'object' && !Array.isArray(value)
              ? 'a mapping here is a group — add it above instead'
              : null
          }
          onApply={(extras) => dispatch({ type: 'patch-lab', patch: { groupsExtras: extras } })}
          placeholder={'settings beside the groups, e.g.\n_auto_create: true'}
        />
      )}
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
  const vrfCount = vrfsOwned ? 0 : doc.vrfs.length
  const labExtrasCount = Object.keys(doc.extras).length

  return (
    <div className="flex flex-col gap-4">
      <SectionTitle>lab settings</SectionTitle>

      <Tabs defaultValue="defaults">
        <TabsList className="w-full">
          <InspectorTab value="defaults">Defaults</InspectorTab>
          <InspectorTab value="vrfs">VRFs{countSuffix(vrfCount)}</InspectorTab>
          <InspectorTab value="groups">Groups{countSuffix(doc.groups.length)}</InspectorTab>
          <InspectorTab value="advanced">Advanced{countSuffix(labExtrasCount)}</InspectorTab>
        </TabsList>

        <InspectorTabContent value="defaults">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="build-default-device">Default device</Label>
        <DevicePicker
          id="build-default-device"
          devices={devices}
          value={doc.defaultDevice}
          emptyLabel="(none — every node picks its own)"
          onChange={(defaultDevice) => dispatch({ type: 'patch-lab', patch: { defaultDevice } })}
        />
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
              offered={offeredModules(devices, doc.modules)}
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
        </InspectorTabContent>

        <InspectorTabContent value="vrfs">
      {vrfsOwned && (
        <p className="text-xs text-muted-foreground">
          The vrfs carry attributes (rd, rt, …) the controls can&apos;t edit — managed in
          Advanced properties.
        </p>
      )}
      {!vrfsOwned && !doc.modules.includes('vrf') && (
        <p className="text-xs text-muted-foreground">
          Enable the vrf module (Defaults tab) to declare VRFs.
        </p>
      )}
      {!vrfsOwned && doc.modules.includes('vrf') && (
        <div className="flex flex-col gap-1.5">
          {doc.vrfs.length === 0 && (
            <p className="text-xs text-muted-foreground">None yet — add one to place customer sites.</p>
          )}
          {doc.vrfs.map(({ name: vrf, extras }) => {
            const members = memberCount(vrf)
            const remove = () => dispatch({ type: 'remove-vrf', name: vrf })
            return (
              <div key={vrf} className="flex flex-col gap-1 rounded-[2px] border px-2 py-1">
              <div className="flex items-center justify-between gap-2">
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
              {/* rd, rt, import/export: netlab derives them when absent, so
                  they stay YAML rather than becoming four more controls. */}
              <ExtrasEditor
                key={JSON.stringify(extras ?? {})}
                idPrefix={`build-vrf-${vrf}`}
                label={`${vrf} attributes`}
                value={extras}
                keyError={() => null}
                onApply={(next) => dispatch({ type: 'patch-vrf', name: vrf, extras: next })}
                placeholder={'vrf attributes, e.g.\nrd: "65000:1"\nexport: [ "65000:1" ]'}
              />
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
        </InspectorTabContent>

        <InspectorTabContent value="groups">
          <GroupsSection
            doc={doc}
            labName={labName}
            groupStyles={groupStyles}
            onGroupColor={onGroupColor}
            dispatch={dispatch}
          />
        </InspectorTabContent>

        <InspectorTabContent value="advanced">
          <ExtrasEditor
            key={JSON.stringify(doc.extras)}
            idPrefix="build-lab"
            value={doc.extras}
            keyError={labExtrasKeyError}
            onApply={(extras) => dispatch({ type: 'patch-lab', patch: { extras: extras ?? {} } })}
            bare
          />
        </InspectorTabContent>
      </Tabs>
    </div>
  )
}

// Template names share the lab/node identifier charset (server-enforced).
const TEMPLATE_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/

/** "Save as template" (delta 21): snapshot this node's attributes — minus its
 * name — into the deployment-wide node collection. Rendered only for holders
 * of the GLOBAL template:manage (the library-authoring gate). */
function SaveNodeTemplate({ doc, node }: { doc: BuildDoc; node: BuildNode }) {
  const { data: me } = useQuery(meQueryOptions)
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(node.name)
  const [description, setDescription] = useState('')
  // A template must STATE its device (it stamps into labs with other
  // defaults), so a node riding the doc's defaults.device gets it written
  // into the fragment explicitly.
  const device = node.device ?? doc.defaultDevice
  const fragment = device === undefined ? null : emitNodeFragment({ ...node, device })
  const save = useMutation({
    mutationFn: (content: string) => api.createNodeTemplate({ name, description, content }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: nodeTemplatesQueryOptions.queryKey })
      toast.success(`Node template ${created.name} saved — it's now in the Add menu`)
      setOpen(false)
    },
    onError: (err) => toastError(err, 'Saving the template failed'),
  })
  if (!(me?.permissions.includes('template:manage') ?? false)) return null
  const invalidName = !TEMPLATE_NAME_RE.test(name) || name.length > 64
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="justify-start gap-2 text-muted-foreground"
        disabled={fragment === null}
        title={
          fragment === null
            ? 'The node needs a device (and something to save) first'
            : 'Save this node’s attributes as a reusable template'
        }
        onClick={() => {
          setName(node.name)
          setDescription('')
          setOpen(true)
        }}
      >
        <Bookmark className="size-3.5" />
        Save as template
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save node as template</DialogTitle>
            <DialogDescription>
              Snapshots this node&apos;s attributes (device, modules, protocol settings, advanced
              properties — not its name or links) into the deployment-wide library. Anyone can
              stamp it from the builder&apos;s Add menu.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="node-template-name">Template name</Label>
              <Input
                id="node-template-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                aria-invalid={name.length > 0 && invalidName}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="node-template-description">Description</Label>
              <Input
                id="node-template-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="What this node is set up as"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={
                fragment === null || invalidName || description.trim() === '' || save.isPending
              }
              onClick={() => {
                if (fragment !== null) save.mutate(fragment)
              }}
            >
              {save.isPending ? 'Saving…' : 'Save template'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function NodeInspector({
  doc,
  labName,
  node,
  dispatch,
  onDuplicate,
  onCopy,
}: {
  doc: BuildDoc
  labName: string
  node: BuildNode
  dispatch: Dispatch<BuilderAction>
  onDuplicate: () => void
  onCopy: () => void
}) {
  const { devices } = useDeviceCatalog()
  const templates = useQuery(customConfigQueryOptions(labName))
  const templateRecords = templates.data?.templates ?? []
  // Everything this node may legally attach to, judged by the SAME rule the
  // canvas drag uses — including itself (netlab gives a self-link two
  // interfaces on one link).
  const [linkTarget, setLinkTarget] = useState('')
  const connectTargets = [
    ...doc.nodes.map((entry) => ({
      id: entry.name,
      label: entry.name === node.name ? `${entry.name} (self-link)` : entry.name,
    })),
    ...doc.links.flatMap((link) =>
      link.kind === 'lan'
        ? [{ id: link.id, label: link.name ?? `${link.members.length}-node LAN` }]
        : [],
    ),
  ].filter((option) => validateConnect(doc, node.name, option.id).ok)
  // A cleared field drops the key; an empty loopback drops the mapping.
  const setLoopback = (key: 'ipv4' | 'ipv6', raw: string) => {
    const next: BuildNodeLoopback = { ...node.loopback }
    if (raw === '') delete next[key]
    else next[key] = raw
    const empty =
      next.ipv4 === undefined && next.ipv6 === undefined && next.extras === undefined
    dispatch({ type: 'patch-node', name: node.name, patch: { loopback: empty ? undefined : next } })
  }
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
  const hasProtocol =
    effectiveModules.includes('bgp') ||
    vrfNames.length > 0 ||
    vrfsOwned ||
    mplsVpnReady ||
    node.mplsVpn === true
  const protocolCount =
    (node.bgpAs !== undefined ? 1 : 0) +
    (node.mplsVpn === true ? 1 : 0) +
    Object.keys(node.vrfs ?? {}).length +
    (vrfsOwned ? 1 : 0)
  const advancedCount =
    (node.image !== undefined ? 1 : 0) +
    (node.role !== undefined ? 1 : 0) +
    (node.loopback !== undefined ? 1 : 0) +
    (node.config !== undefined ? 1 : 0) +
    Object.keys(node.extras ?? {}).length

  return (
    <div className="flex flex-col gap-4">
      <SectionTitle>node</SectionTitle>

      <Tabs defaultValue="general">
        <TabsList className="w-full">
          <InspectorTab value="general">General</InspectorTab>
          <InspectorTab value="protocols">Protocols{countSuffix(protocolCount)}</InspectorTab>
          <InspectorTab value="advanced">Advanced{countSuffix(advancedCount)}</InspectorTab>
        </TabsList>

        <InspectorTabContent value="general">
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

      {/* A duplicate carries the node's settings and group memberships but no
          links — the copy is a new node, not a second attachment. */}
      <div className="flex items-center gap-1.5">
        <Button variant="outline" size="sm" className="flex-1" onClick={onDuplicate}>
          <CopyPlus className="size-3.5" />
          Duplicate
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="flex-1"
          title="Copy this node (Ctrl+C), then paste it from the canvas toolbar"
          onClick={onCopy}
        >
          <Copy className="size-3.5" />
          Copy
        </Button>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="build-node-device">Device</Label>
        <DevicePicker
          id="build-node-device"
          devices={devices}
          value={node.device}
          {...(doc.defaultDevice !== undefined && {
            emptyLabel: `default (${doc.defaultDevice})`,
          })}
          onChange={(device) => dispatch({ type: 'patch-node', name: node.name, patch: { device } })}
        />
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
            offered={offeredModules(devices, effectiveModules)}
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

      <Separator />
      {/* Linking without dragging. The canvas grip stays the quick path, but
          it needs aim and a visible target — this one is precise, reachable
          from the keyboard, and names what it will attach to. Both paths go
          through validateConnect, so they accept exactly the same links. */}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="build-node-connect">Connect to</Label>
        <div className="flex items-center gap-1.5">
          <Select value={linkTarget} onValueChange={setLinkTarget}>
            <SelectTrigger id="build-node-connect" size="sm" className="flex-1">
              <SelectValue
                placeholder={connectTargets.length === 0 ? 'nothing to connect to' : 'pick a target'}
              />
            </SelectTrigger>
            <SelectContent>
              {connectTargets.map((option) => (
                <SelectItem key={option.id} value={option.id}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            disabled={linkTarget === ''}
            onClick={() => {
              dispatch({ type: 'connect', source: node.name, target: linkTarget })
              setLinkTarget('')
            }}
          >
            <Waypoints className="size-3.5" />
            Link
          </Button>
        </div>
      </div>
      <Button
        variant="ghost"
        size="sm"
        className="justify-start gap-2 text-muted-foreground"
        title="A one-endpoint link — netlab resolves it to a loopback interface"
        onClick={() => dispatch({ type: 'add-stub', id: nextStubId(doc), node: node.name })}
      >
        <CircleDot className="size-3.5" />
        Add stub link
      </Button>
      <SaveNodeTemplate doc={doc} node={node} />
      <Button
        variant="outline"
        size="sm"
        className="justify-start gap-2 text-destructive"
        onClick={() => dispatch({ type: 'delete-node', name: node.name })}
      >
        <Trash2 className="size-3.5" />
        Delete node (removes its links)
      </Button>
        </InspectorTabContent>

        <InspectorTabContent value="protocols">
      {!hasProtocol && (
        <p className="text-xs text-muted-foreground">
          Enable bgp, mpls or vrf modules (General tab) to configure protocol behavior.
        </p>
      )}
      {hasProtocol && (
        <>
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
            const setVrfs = (next: Record<string, BuildNodeVrf>) =>
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
                          // keep whatever else this node says about the vrf
                          [vrf]: {
                            ...membership,
                            ...(checked === true ? { loopback: true } : { loopback: undefined }),
                          },
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
        </>
      )}
        </InspectorTabContent>

        <InspectorTabContent value="advanced">
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
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="build-node-role">Role</Label>
            <Select
              value={node.role ?? 'default'}
              onValueChange={(value) =>
                dispatch({
                  type: 'patch-node',
                  name: node.name,
                  patch: { role: value === 'default' ? undefined : (value as NodeRole) },
                })
              }
            >
              <SelectTrigger id="build-node-role" size="sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">(the device&apos;s own role)</SelectItem>
                {NODE_ROLES.map((role) => (
                  <SelectItem key={role} value={role}>
                    {role}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="build-node-loopback4">Loopback IPv4</Label>
            <Input
              id="build-node-loopback4"
              className="h-8 font-mono"
              placeholder="from the loopback pool"
              value={node.loopback?.ipv4 ?? ''}
              onChange={(event) => setLoopback('ipv4', event.target.value)}
            />
            <Label htmlFor="build-node-loopback6">Loopback IPv6</Label>
            <Input
              id="build-node-loopback6"
              className="h-8 font-mono"
              placeholder="from the loopback pool"
              value={node.loopback?.ipv6 ?? ''}
              onChange={(event) => setLoopback('ipv6', event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              netlab creates a loopback interface for router-role devices only.
            </p>
          </div>
          <ConfigTemplatePicker
            idPrefix={`build-node-${node.name}`}
            offers={nodeTemplateOffers(templateRecords, doc, node.name)}
            config={node.config ?? []}
            onChange={(next) =>
              dispatch({
                type: 'patch-node',
                name: node.name,
                patch: { config: next.length > 0 ? next : undefined },
              })
            }
          />
          <ExtrasEditor
            key={JSON.stringify(node.extras ?? {})}
            idPrefix={`build-node-${node.name}`}
            value={node.extras}
            keyError={nodeExtrasKeyError}
            onApply={(extras) =>
              dispatch({ type: 'patch-node', name: node.name, patch: { extras } })
            }
            bare
          />
        </InspectorTabContent>
      </Tabs>
    </div>
  )
}

function LinkNameInput({
  link,
  linkIndex,
  dispatch,
}: {
  link: BuildLink
  linkIndex: number
  dispatch: Dispatch<BuilderAction>
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={`build-link-${linkIndex}-name`}>Name</Label>
      <Input
        id={`build-link-${linkIndex}-name`}
        className="h-8 font-mono"
        placeholder="unnamed"
        value={link.name ?? ''}
        onChange={(event) =>
          dispatch({ type: 'patch-link', linkIndex, patch: { name: event.target.value } })
        }
      />
    </div>
  )
}

/** A number field that clears its key when emptied. netlab's own bounds are
 * the min/max — the dry create is still the judge, this just stops the
 * obvious typo. */
function LinkNumberInput({
  id,
  label,
  value,
  placeholder,
  min,
  max,
  onChange,
}: {
  id: string
  label: string
  value: number | undefined
  placeholder: string
  min?: number
  max?: number
  onChange: (next: number | undefined) => void
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        className="h-8 font-mono"
        placeholder={placeholder}
        min={min}
        max={max}
        value={value ?? ''}
        onChange={(event) => {
          const raw = event.target.value
          if (raw === '') return onChange(undefined)
          const parsed = Number(raw)
          if (Number.isFinite(parsed)) onChange(parsed)
        }}
      />
    </div>
  )
}

/** The link's addressing and sizing: netlab's `prefix`, `bandwidth`, `mtu`.
 * `prefix: false` is the L2 spelling — an unnumbered wire, which is what
 * config import emits for a link whose endpoints carry no address and what a
 * self-link needs. */
function LinkAttrInputs({
  link,
  linkIndex,
  dispatch,
}: {
  link: BuildLink
  linkIndex: number
  dispatch: Dispatch<BuilderAction>
}) {
  const patch = (next: Partial<Pick<LinkAttrs, 'prefix' | 'bandwidth' | 'mtu'>>) =>
    dispatch({ type: 'patch-link', linkIndex, patch: next })
  const unnumbered = link.prefix === false
  return (
    <>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`build-link-${linkIndex}-prefix`}>Prefix</Label>
        <Input
          id={`build-link-${linkIndex}-prefix`}
          className="h-8 font-mono"
          placeholder={unnumbered ? 'none (L2 link)' : 'from the pool'}
          disabled={unnumbered}
          value={typeof link.prefix === 'string' ? link.prefix : ''}
          onChange={(event) =>
            patch({ prefix: event.target.value === '' ? undefined : event.target.value })
          }
        />
        <div className="flex items-center gap-2">
          <Checkbox
            id={`build-link-${linkIndex}-l2`}
            checked={unnumbered}
            onCheckedChange={(checked) => patch({ prefix: checked === true ? false : undefined })}
          />
          <Label
            htmlFor={`build-link-${linkIndex}-l2`}
            className="text-xs font-normal text-muted-foreground"
          >
            no addressing (L2 link)
          </Label>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <LinkNumberInput
          id={`build-link-${linkIndex}-bandwidth`}
          label="Bandwidth"
          placeholder="kbps"
          min={1}
          value={link.bandwidth}
          onChange={(bandwidth) => patch({ bandwidth })}
        />
        <LinkNumberInput
          id={`build-link-${linkIndex}-mtu`}
          label="MTU"
          placeholder="bytes"
          min={64}
          max={9216}
          value={link.mtu}
          onChange={(mtu) => patch({ mtu })}
        />
      </div>
    </>
  )
}

/** Link-level attributes (bandwidth, mtu, prefix, …). The classifier refuses
 * keys naming declared nodes — those would re-parse as endpoints. */
function LinkAdvanced({
  doc,
  link,
  linkIndex,
  dispatch,
  bare,
}: {
  doc: BuildDoc
  link: BuildLink
  linkIndex: number
  dispatch: Dispatch<BuilderAction>
  bare?: boolean
}) {
  const endpointNames = declaredNodes(doc.nodes)
  return (
    <ExtrasEditor
      key={JSON.stringify(link.extras ?? {})}
      idPrefix={`build-link-${linkIndex}`}
      value={link.extras}
      keyError={(key, value) => linkExtrasKeyError(key, value, endpointNames)}
      onApply={(extras) => dispatch({ type: 'patch-link', linkIndex, patch: { extras } })}
      placeholder={'link attributes, e.g.\nbandwidth: 100000\nmtu: 9000'}
      bare={bare}
    />
  )
}

/** One endpoint: its interface name and addresses (typed — the fidelity an
 * imported lab depends on), then everything else as YAML. `ipv4: false` is
 * its own control because a BARE endpoint on an addressed link gets an
 * address invented for it, which is not the same thing as "no address". */
function EndpointFields({
  endpoint,
  linkIndex,
  endpointIndex,
  dispatch,
  bare,
}: {
  endpoint: LinkEndpoint
  linkIndex: number
  // Endpoints are addressed by position: a self-link has the same node twice.
  endpointIndex: number
  dispatch: Dispatch<BuilderAction>
  bare?: boolean
}) {
  const patch = (next: EndpointPatch) =>
    dispatch({ type: 'patch-endpoint', linkIndex, endpointIndex, patch: next })
  const id = `build-link-${linkIndex}-${endpointIndex}`
  const unaddressed = endpoint.ipv4 === false
  return (
    <>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-ifname`}>Interface name</Label>
        <Input
          id={`${id}-ifname`}
          className="h-8 font-mono"
          placeholder="netlab assigns one"
          value={endpoint.ifname ?? ''}
          onChange={(event) => patch({ ifname: event.target.value })}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-ipv4`}>IPv4</Label>
        <Input
          id={`${id}-ipv4`}
          className="h-8 font-mono"
          placeholder={unaddressed ? 'none' : 'from the link prefix'}
          disabled={unaddressed}
          value={typeof endpoint.ipv4 === 'string' ? endpoint.ipv4 : ''}
          onChange={(event) => patch({ ipv4: event.target.value })}
        />
        <div className="flex items-center gap-2">
          <Checkbox
            id={`${id}-noipv4`}
            checked={unaddressed}
            onCheckedChange={(checked) => patch({ ipv4: checked === true ? false : undefined })}
          />
          <Label htmlFor={`${id}-noipv4`} className="text-xs font-normal text-muted-foreground">
            no IPv4 here (netlab invents one otherwise)
          </Label>
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-ipv6`}>IPv6</Label>
        <Input
          id={`${id}-ipv6`}
          className="h-8 font-mono"
          placeholder="from the link prefix"
          disabled={endpoint.ipv6 === false}
          value={typeof endpoint.ipv6 === 'string' ? endpoint.ipv6 : ''}
          onChange={(event) => patch({ ipv6: event.target.value })}
        />
      </div>
      <ExtrasEditor
        key={JSON.stringify(endpoint.extras ?? {})}
        idPrefix={id}
        label={`${endpoint.node} attributes`}
        value={endpoint.extras}
        keyError={(key, value) => {
          if (key === 'ifname' && typeof value === 'string') return 'use the Interface name field'
          if ((key === 'ipv4' || key === 'ipv6') && (typeof value === 'string' || value === false)) {
            return `use the ${key.toUpperCase()} field`
          }
          return null
        }}
        onApply={(extras) => patch({ extras })}
        placeholder={'per-endpoint attributes, e.g.\nospf.cost: 100'}
        bare={bare}
      />
    </>
  )
}

/** netlab derives an interface address from the link prefix and the NODE's id,
 * so both ends of a self-link draw the SAME address and `netlab create` fails
 * with "Duplicate address" (verified against netlab 26.07). Two spellings
 * avoid it, and the link is fine either way — so this warns where the user is
 * editing instead of blocking a save the server would judge anyway. */
function SelfLinkAddressingHint({ link }: { link: BuildLink }) {
  if (link.kind !== 'p2p' || link.a.node !== link.b.node) return null
  const addressed = link.a.extras?.['ipv4'] !== undefined && link.b.extras?.['ipv4'] !== undefined
  if (link.prefix === false || addressed) return null
  return (
    <p className="text-xs text-muted-foreground">
      Both ends of a self-link would take the same address from the link prefix, which netlab
      rejects. Tick <span className="font-mono">no addressing</span> for an L2 link, or set an{' '}
      <span className="font-mono">ipv4</span> on each end.
    </p>
  )
}

const extrasCount = (extras: Record<string, unknown> | undefined): number =>
  Object.keys(extras ?? {}).length

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
  onDuplicateNode,
  onCopyNode,
}: {
  state: BuilderState
  labName: string
  groupStyles: GroupStyles
  onGroupColor: (group: string, color: string) => void
  dispatch: Dispatch<BuilderAction>
  // Duplicate and copy live in the Build tab: both place the new node
  // relative to its source, and placement is layout state the reducer does
  // not own.
  onDuplicateNode: (name: string) => void
  onCopyNode: () => void
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
      return (
        <NodeInspector
          key={node.name}
          doc={doc}
          labName={labName}
          node={node}
          dispatch={dispatch}
          onDuplicate={() => onDuplicateNode(node.name)}
          onCopy={onCopyNode}
        />
      )
    }
    case 'link': {
      const link = doc.links[selection.linkIndex]
      if (link === undefined || link.kind !== 'p2p') return lab
      return (
        <div className="flex flex-col gap-4">
          <SectionTitle>link</SectionTitle>
          <p className="font-mono text-sm">
            {link.a.node} ↔ {link.b.node}
            {link.a.node === link.b.node && (
              <span className="ml-2 font-sans text-xs text-muted-foreground">
                self-link — two interfaces on one node
              </span>
            )}
          </p>
          <SelfLinkAddressingHint link={link} />
          <Tabs defaultValue="general">
            <TabsList className="w-full">
              <InspectorTab value="general">General</InspectorTab>
              <InspectorTab value="ep-a">
                {/* A self-link's ends share a name, so they wear their position. */}
                <span className="truncate font-mono">
                  {link.a.node}
                  {link.a.node === link.b.node ? ' #1' : ''}
                </span>
                {countSuffix(extrasCount(link.a.extras))}
              </InspectorTab>
              <InspectorTab value="ep-b">
                <span className="truncate font-mono">
                  {link.b.node}
                  {link.a.node === link.b.node ? ' #2' : ''}
                </span>
                {countSuffix(extrasCount(link.b.extras))}
              </InspectorTab>
              <InspectorTab value="advanced">
                Advanced{countSuffix(extrasCount(link.extras))}
              </InspectorTab>
            </TabsList>
            <InspectorTabContent value="general">
              <LinkNameInput link={link} linkIndex={selection.linkIndex} dispatch={dispatch} />
              <LinkAttrInputs link={link} linkIndex={selection.linkIndex} dispatch={dispatch} />
              <Separator />
              <Button
                variant="outline"
                size="sm"
                className="justify-start gap-2 text-destructive"
                onClick={() => dispatch({ type: 'delete-link', linkIndex: selection.linkIndex })}
              >
                <Unlink className="size-3.5" />
                Delete link
              </Button>
            </InspectorTabContent>
            <InspectorTabContent value="ep-a">
              <EndpointFields
                endpoint={link.a}
                linkIndex={selection.linkIndex}
                endpointIndex={0}
                dispatch={dispatch}
                bare
              />
            </InspectorTabContent>
            <InspectorTabContent value="ep-b">
              <EndpointFields
                endpoint={link.b}
                linkIndex={selection.linkIndex}
                endpointIndex={1}
                dispatch={dispatch}
                bare
              />
            </InspectorTabContent>
            <InspectorTabContent value="advanced">
              <LinkAdvanced
                doc={doc}
                link={link}
                linkIndex={selection.linkIndex}
                dispatch={dispatch}
                bare
              />
            </InspectorTabContent>
          </Tabs>
        </div>
      )
    }
    case 'stub': {
      const link = doc.links[selection.linkIndex]
      if (link === undefined || link.kind !== 'stub') return lab
      return (
        <div className="flex flex-col gap-4">
          <SectionTitle>stub link</SectionTitle>
          <p className="font-mono text-sm">{link.endpoint.node}</p>
          <p className="text-xs text-muted-foreground">
            One endpoint — netlab resolves it to a loopback interface on the node.
          </p>
          <Tabs defaultValue="general">
            <TabsList className="w-full">
              <InspectorTab value="general">General</InspectorTab>
              <InspectorTab value="endpoint">
                <span className="truncate font-mono">{link.endpoint.node}</span>
                {countSuffix(extrasCount(link.endpoint.extras))}
              </InspectorTab>
              <InspectorTab value="advanced">
                Advanced{countSuffix(extrasCount(link.extras))}
              </InspectorTab>
            </TabsList>
            <InspectorTabContent value="general">
              <LinkNameInput link={link} linkIndex={selection.linkIndex} dispatch={dispatch} />
              <LinkAttrInputs link={link} linkIndex={selection.linkIndex} dispatch={dispatch} />
              <Separator />
              <Button
                variant="outline"
                size="sm"
                className="justify-start gap-2 text-destructive"
                onClick={() => dispatch({ type: 'delete-link', linkIndex: selection.linkIndex })}
              >
                <Trash2 className="size-3.5" />
                Delete stub link
              </Button>
            </InspectorTabContent>
            <InspectorTabContent value="endpoint">
              <EndpointFields
                endpoint={link.endpoint}
                linkIndex={selection.linkIndex}
                endpointIndex={0}
                dispatch={dispatch}
                bare
              />
            </InspectorTabContent>
            <InspectorTabContent value="advanced">
              <LinkAdvanced
                doc={doc}
                link={link}
                linkIndex={selection.linkIndex}
                dispatch={dispatch}
                bare
              />
            </InspectorTabContent>
          </Tabs>
        </div>
      )
    }
    case 'lan': {
      const link = doc.links[selection.linkIndex]
      if (link === undefined || link.kind !== 'lan') return lab
      return (
        <div className="flex flex-col gap-4">
          <SectionTitle>lan segment</SectionTitle>
          <Tabs defaultValue="general">
            <TabsList className="w-full">
              <InspectorTab value="general">General</InspectorTab>
              <InspectorTab value="advanced">
                Advanced{countSuffix(extrasCount(link.extras))}
              </InspectorTab>
            </TabsList>
            <InspectorTabContent value="general">
          {link.members.length === 0 && (
            <p className="text-xs text-muted-foreground">
              No members yet — drag from a node onto this segment.
            </p>
          )}
          {link.members.map((member, memberIndex) => (
            <div
              key={`${member.node}-${memberIndex}`}
              className="flex items-center justify-between gap-2 rounded-[2px] border px-2 py-1"
            >
              <span className="font-mono text-sm">{member.node}</span>
              <Button
                variant="ghost"
                size="icon-xs"
                title={`Remove ${member.node} from the segment`}
                onClick={() =>
                  dispatch({
                    type: 'remove-member',
                    linkIndex: selection.linkIndex,
                    endpointIndex: memberIndex,
                  })
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
          <LinkNameInput link={link} linkIndex={selection.linkIndex} dispatch={dispatch} />
              <LinkAttrInputs link={link} linkIndex={selection.linkIndex} dispatch={dispatch} />
          <Separator />
          <Button
            variant="outline"
            size="sm"
            className="justify-start gap-2 text-destructive"
            onClick={() => dispatch({ type: 'delete-link', linkIndex: selection.linkIndex })}
          >
            <Trash2 className="size-3.5" />
            Delete segment
          </Button>
            </InspectorTabContent>
            <InspectorTabContent value="advanced">
              <LinkAdvanced
                doc={doc}
                link={link}
                linkIndex={selection.linkIndex}
                dispatch={dispatch}
                bare
              />
            </InspectorTabContent>
          </Tabs>
        </div>
      )
    }
    case 'member': {
      const link = doc.links[selection.linkIndex]
      if (link === undefined || link.kind !== 'lan') return lab
      const member = link.members[selection.endpointIndex]
      if (member === undefined) return lab
      return (
        <div className="flex flex-col gap-4">
          <SectionTitle>lan membership</SectionTitle>
          <p className="font-mono text-sm">
            {member.node} on {link.name ?? link.id}
          </p>
          <EndpointFields
            endpoint={member}
            linkIndex={selection.linkIndex}
            endpointIndex={selection.endpointIndex}
            dispatch={dispatch}
            bare
          />
          <Separator />
          <Button
            variant="outline"
            size="sm"
            className="justify-start gap-2 text-destructive"
            onClick={() =>
              dispatch({
                type: 'remove-member',
                linkIndex: selection.linkIndex,
                endpointIndex: selection.endpointIndex,
              })
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
