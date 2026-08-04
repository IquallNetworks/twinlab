import { parse, stringify } from 'yaml'

import { BUILDER_MODULES, FALLBACK_DEVICE_CATALOG, type BuilderModule } from './device-catalog'

// The builder's document model: a typed core the visual controls edit, plus
// LOSSLESS `extras` passthrough at the lab, node and group level. Every key of
// a definition lives in exactly ONE of the two — the typed model when it has
// the exact shape a control can edit, `extras` (preserved verbatim, edited as
// YAML in the inspector's advanced sections) otherwise. parseBuildDoc gates
// only on STRUCTURE the canvas can't represent (exotic link forms, invalid
// names, unknown devices — a policy gate, not a data one); unknown or
// overflow DATA never gates and is never dropped.
//
// Typed core: nodes + p2p/LAN links, groups (members + config templates), the
// proven module set (ospf/bgp/mpls/vrf) with bgp.as, mpls.ldp, mpls.vpn and
// vrf membership, the curated device catalog, and the keys the backend itself
// injects on save (name, addressing.mgmt). Emission is canonical; the
// round-trip invariant is: for any doc emitBuildDoc accepts,
// parseBuildDoc(emit(doc)) equals doc (up to LAN ids, which are session
// metadata).
//
// Pure module (no React, no `@/` alias imports) so a plain node script can
// exercise the round-trip.

export { BUILDER_MODULES, type BuilderModule } from './device-catalog'

export type Extras = Record<string, unknown>

export interface BuildNodeVrf {
  loopback?: boolean
}

export interface BuildNode {
  name: string
  device?: string
  image?: string
  // undefined → the node inherits the global module list; [] → explicitly none.
  modules?: BuilderModule[]
  bgpAs?: number
  mplsVpn?: boolean
  vrfs?: Record<string, BuildNodeVrf>
  // Attributes outside the typed set, preserved verbatim.
  extras?: Extras
}

export interface BuildGroup {
  name: string
  members: string[]
  // Custom-config templates attached to the members (netlab `config: [...]`).
  config?: string[]
  // Everything else a group broadcasts (module, bgp.as, _auto_create, …).
  extras?: Extras
}

export type BuildLink =
  // Emitted as the "a-b" string form (safe: builder names cannot carry '-').
  | { kind: 'p2p'; a: string; b: string }
  // 3+ endpoints, emitted as a member list. Ids are `lan:<n>` in document
  // order — the SAME scheme as lib/topology.ts, so manual canvas layouts
  // keyed by these ids carry across the Topology and Build tabs.
  | { kind: 'lan'; id: string; members: string[] }

export interface MgmtAddressing {
  mgmt: { ipv4: string; _network?: string }
}

export interface BuildDoc {
  // Injected by the backend on save (the record's name is re-pinned); the
  // builder preserves it verbatim and never edits it.
  name?: string
  provider?: string
  defaultDevice?: string
  modules: BuilderModule[]
  bgpAs?: number
  mplsLdp?: boolean
  vrfs: string[]
  groups: BuildGroup[]
  // Injected by the backend on save (the lab's allocated mgmt subnet);
  // preserved verbatim.
  addressing?: MgmtAddressing
  // Top-level keys outside the typed core, preserved verbatim.
  extras: Extras
  nodes: BuildNode[]
  links: BuildLink[]
}

export type BuildDocResult = { ok: true; doc: BuildDoc } | { ok: false; reasons: string[] }
export type EmitResult = { ok: true; yaml: string } | { ok: false; problems: string[] }

// As-you-type rule for NEW names in the builder. Hyphens are structurally
// unsafe (the "a-b" link form splits on them); lowercase keeps emitted
// definitions uniform.
export const NODE_NAME_RE = /^[a-z_][a-z0-9_]*$/
export const NODE_NAME_MAX = 24

// Existing hand-written definitions get a case-tolerant rule: uppercase names
// emit and round-trip fine, only the structural constraints matter.
const EXISTING_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function describe(value: unknown): string {
  if (typeof value === 'string') return `"${value}"`
  if (value === null) return 'null'
  if (Array.isArray(value)) return 'a list'
  if (typeof value === 'object') return 'a mapping'
  return String(value)
}

// --------------------------------------------------------------------------
// Shape classifiers — ONE source of truth for "does this key/value have the
// exact shape a typed control edits?". parseBuildDoc uses them to split typed
// vs extras; the advanced editors use them to refuse keys the controls own.
// --------------------------------------------------------------------------

function modulesShape(value: unknown): BuilderModule[] | null {
  if (!Array.isArray(value)) return null
  const modules: BuilderModule[] = []
  for (const entry of value) {
    if (typeof entry !== 'string' || !(BUILDER_MODULES as readonly string[]).includes(entry)) {
      return null
    }
    modules.push(entry as BuilderModule)
  }
  return modules
}

function bgpShape(value: unknown): number | null {
  return isRecord(value) && Object.keys(value).length === 1 && typeof value['as'] === 'number'
    ? value['as']
    : null
}

function mplsBoolShape(value: unknown, key: 'ldp' | 'vpn'): boolean | null {
  return isRecord(value) && Object.keys(value).length === 1 && typeof value[key] === 'boolean'
    ? value[key]
    : null
}

/** Top-level vrfs in the typed shape: a mapping of bare declarations (every
 * vrf empty). Any vrf carrying attributes (rd, rt, …) → the whole key is
 * extras territory. */
function vrfListShape(value: unknown): string[] | null {
  if (!isRecord(value)) return null
  const names: string[] = []
  for (const [name, attrs] of Object.entries(value)) {
    if (!EXISTING_NAME_RE.test(name) || name.length > NODE_NAME_MAX) return null
    if (attrs !== null && !(isRecord(attrs) && Object.keys(attrs).length === 0)) return null
    names.push(name)
  }
  return names
}

/** Node vrf membership in the typed shape: each entry empty or exactly
 * `{loopback: bool}`. Declaration against the top-level vrfs is checked at
 * emit (a save blocker), not here — shape and reference are different rules. */
function nodeVrfsShape(value: unknown): Record<string, BuildNodeVrf> | null {
  if (!isRecord(value)) return null
  const vrfs: Record<string, BuildNodeVrf> = {}
  for (const [vrfName, attrs] of Object.entries(value)) {
    if (attrs === null) {
      vrfs[vrfName] = {}
      continue
    }
    if (!isRecord(attrs)) return null
    const entry: BuildNodeVrf = {}
    for (const [key, attr] of Object.entries(attrs)) {
      if (key !== 'loopback' || typeof attr !== 'boolean') return null
      entry.loopback = attr
    }
    vrfs[vrfName] = entry
  }
  return vrfs
}

function mgmtAddressingShape(value: unknown): MgmtAddressing | null {
  if (!isRecord(value) || Object.keys(value).length !== 1) return null
  const mgmt = value['mgmt']
  if (!isRecord(mgmt)) return null
  const ipv4 = mgmt['ipv4']
  const network = mgmt['_network']
  if (typeof ipv4 !== 'string') return null
  for (const key of Object.keys(mgmt)) {
    if (key !== 'ipv4' && key !== '_network') return null
  }
  if (network !== undefined && typeof network !== 'string') return null
  return { mgmt: network === undefined ? { ipv4 } : { ipv4, _network: network } }
}

function stringListShape(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null
  return value.every((entry): entry is string => typeof entry === 'string')
    ? (value as string[])
    : null
}

/** Advanced-editor validation, lab level: null = fine as an extra; a message
 * = the builder's controls own this key in this shape. */
export function labExtrasKeyError(key: string, value: unknown): string | null {
  switch (key) {
    case 'name':
    case 'provider':
    case 'nodes':
    case 'links':
    case 'groups':
      return `"${key}" is managed by the builder`
    case 'defaults.device':
      return 'set the default device with its control'
    case 'defaults':
      return isRecord(value) && Object.keys(value).length === 1 && 'device' in value
        ? 'set the default device with its control'
        : null
    case 'module':
      return modulesShape(value) !== null ? 'use the Global modules control' : null
    case 'bgp.as':
      return typeof value === 'number' ? 'use the BGP AS control' : null
    case 'bgp':
      return bgpShape(value) !== null ? 'use the BGP AS control' : null
    case 'mpls.ldp':
      return typeof value === 'boolean' ? 'use the LDP transport control' : null
    case 'mpls':
      return mplsBoolShape(value, 'ldp') !== null ? 'use the LDP transport control' : null
    case 'vrfs':
      return vrfListShape(value) !== null ? 'use the VRFs control' : null
    case 'addressing':
      return mgmtAddressingShape(value) !== null
        ? 'the management addressing is backend-managed'
        : null
    default:
      return null
  }
}

/** Advanced-editor validation, node level. */
export function nodeExtrasKeyError(key: string, value: unknown): string | null {
  switch (key) {
    case 'device':
      return typeof value === 'string' ? 'use the Device control' : null
    case 'image':
      return typeof value === 'string' ? 'use the Image override control' : null
    case 'module':
      return modulesShape(value) !== null ? 'use the Modules control' : null
    case 'bgp.as':
      return typeof value === 'number' ? 'use the BGP AS control' : null
    case 'bgp':
      return bgpShape(value) !== null ? 'use the BGP AS control' : null
    case 'mpls.vpn':
      return typeof value === 'boolean' ? 'use the MPLS VPN edge control' : null
    case 'mpls':
      return mplsBoolShape(value, 'vpn') !== null ? 'use the MPLS VPN edge control' : null
    case 'vrfs':
      return nodeVrfsShape(value) !== null ? 'use the VRF membership controls' : null
    default:
      return null
  }
}

/** Advanced-editor validation, group level. */
export function groupExtrasKeyError(key: string, value: unknown): string | null {
  if (key === 'members' && stringListShape(value) !== null) return 'use the member checkboxes'
  if (key === 'config' && stringListShape(value) !== null) return 'use the template picker'
  return null
}

/** The vrf names a node may reference: the typed list plus — when a vrf
 * carries attributes and the whole `vrfs` key rode into extras — the names
 * declared there. */
export function declaredVrfs(doc: BuildDoc): string[] {
  const fromExtras = doc.extras['vrfs']
  return [...doc.vrfs, ...(isRecord(fromExtras) ? Object.keys(fromExtras) : [])]
}

/** True when the advanced properties own this key — the matching typed
 * control should disable itself and point at the advanced editor, because
 * setting both would emit the same key twice. */
export function extrasOwn(extras: Extras | undefined, key: string): boolean {
  return extras !== undefined && key in extras
}

// --------------------------------------------------------------------------
// Parse
// --------------------------------------------------------------------------

function parseDevice(
  value: unknown,
  where: string,
  reasons: string[],
  knownDevices: readonly string[],
): string | undefined {
  // The device gate is POLICY, not shape: an uncataloged device is the
  // accepted-but-unpromised case (CLAUDE.md), edited as text until the NOS
  // sweep widens the set — extras passthrough deliberately does not apply.
  if (typeof value !== 'string') return undefined
  if (!knownDevices.includes(value)) {
    reasons.push(`${where} device "${value}" is not in the builder's catalog`)
    return undefined
  }
  return value
}

function parseNode(
  name: string,
  attrs: unknown,
  reasons: string[],
  knownDevices: readonly string[],
): BuildNode {
  const node: BuildNode = { name }
  if (!EXISTING_NAME_RE.test(name) || name.length > NODE_NAME_MAX) {
    reasons.push(
      `node name "${name}" is outside the builder's rules (letters, digits, underscores; max ${NODE_NAME_MAX})`,
    )
  }
  if (attrs === null || attrs === undefined) return node
  if (!isRecord(attrs)) {
    reasons.push(`node "${name}" must be empty or a mapping of attributes`)
    return node
  }
  const extras: Extras = {}
  for (const [key, value] of Object.entries(attrs)) {
    switch (key) {
      case 'device': {
        const device = parseDevice(value, `node "${name}":`, reasons, knownDevices)
        if (device !== undefined) node.device = device
        else if (typeof value !== 'string') extras[key] = value
        break
      }
      case 'image':
        if (typeof value === 'string') node.image = value
        else extras[key] = value
        break
      case 'module': {
        const modules = modulesShape(value)
        if (modules !== null) node.modules = modules
        else extras[key] = value
        break
      }
      case 'bgp.as':
        if (typeof value === 'number') node.bgpAs = value
        else extras[key] = value
        break
      case 'bgp': {
        const as = bgpShape(value)
        if (as !== null) node.bgpAs = as
        else extras[key] = value
        break
      }
      case 'mpls.vpn':
        if (typeof value === 'boolean') node.mplsVpn = value
        else extras[key] = value
        break
      case 'mpls': {
        const vpn = mplsBoolShape(value, 'vpn')
        if (vpn !== null) node.mplsVpn = vpn
        else extras[key] = value
        break
      }
      case 'vrfs': {
        const vrfs = nodeVrfsShape(value)
        if (vrfs !== null) node.vrfs = vrfs
        else extras[key] = value
        break
      }
      default:
        extras[key] = value
    }
  }
  if (Object.keys(extras).length > 0) node.extras = extras
  return node
}

/** Groups parse per-group: members/config in their exact shapes are typed,
 * every other key rides that group's extras. A groups mapping whose VALUES
 * are not all mappings (e.g. a `_auto_create: true` toggle at the groups
 * level) is preserved whole in the doc extras instead. */
function parseGroups(value: unknown, docExtras: Extras): BuildGroup[] {
  if (!isRecord(value) || Object.values(value).some((attrs) => attrs !== null && !isRecord(attrs))) {
    docExtras['groups'] = value
    return []
  }
  const groups: BuildGroup[] = []
  for (const [name, attrs] of Object.entries(value)) {
    const group: BuildGroup = { name, members: [] }
    const extras: Extras = {}
    if (attrs !== null && isRecord(attrs)) {
      for (const [key, entry] of Object.entries(attrs)) {
        if (key === 'members') {
          const members = stringListShape(entry)
          if (members !== null) group.members = members
          else extras[key] = entry
        } else if (key === 'config') {
          const config = stringListShape(entry)
          if (config !== null) group.config = config
          else extras[key] = entry
        } else {
          extras[key] = entry
        }
      }
    }
    if (Object.keys(extras).length > 0) group.extras = extras
    groups.push(group)
  }
  return groups
}

function parseLinkEndpoints(entry: unknown, index: number, reasons: string[]): string[] | null {
  if (typeof entry === 'string') {
    const parts = entry.split('-').filter((part) => part !== '')
    if (parts.length < 2) {
      reasons.push(`link ${index + 1} ("${entry}") is not an "a-b" endpoint pair`)
      return null
    }
    return parts
  }
  if (Array.isArray(entry)) {
    const members = entry.filter((member): member is string => typeof member === 'string')
    if (members.length !== entry.length || members.length < 2) {
      reasons.push(`link ${index + 1} must be a list of at least two node names`)
      return null
    }
    return members
  }
  reasons.push(
    `link ${index + 1} uses a form the builder can't represent (attributes, interfaces, or link groups)`,
  )
  return null
}

function parseLinks(
  value: unknown,
  declared: ReadonlySet<string>,
  reasons: string[],
): BuildLink[] {
  if (value === undefined) return []
  if (!Array.isArray(value)) {
    reasons.push('"links" must be a list (the dict-of-lists form is text-editor territory)')
    return []
  }
  const links: BuildLink[] = []
  let lanCount = 0
  value.forEach((entry, index) => {
    const endpoints = parseLinkEndpoints(entry, index, reasons)
    if (endpoints === null) return
    const undeclaredEndpoint = endpoints.find((name) => !declared.has(name))
    if (undeclaredEndpoint !== undefined) {
      reasons.push(`link ${index + 1} references undeclared node "${undeclaredEndpoint}"`)
      return
    }
    if (new Set(endpoints).size !== endpoints.length) {
      reasons.push(`link ${index + 1} connects a node to itself`)
      return
    }
    if (endpoints.length === 2) {
      const [a, b] = endpoints as [string, string]
      links.push({ kind: 'p2p', a, b })
    } else {
      lanCount += 1
      links.push({ kind: 'lan', id: `lan:${lanCount}`, members: endpoints })
    }
  })
  return links
}

/** The structural gate: parse a stored definition into the builder's model,
 * collecting EVERY reason it can't be represented (never fail-fast — the
 * notice lists them all). Data outside the typed core does not gate — it
 * lands verbatim in the extras. */
export function parseBuildDoc(
  definition: string,
  // The device slugs the builder may represent — the server catalog's set
  // when available; the static fallback keeps the pure round-trip harness
  // (and a degraded backend) working.
  knownDevices: readonly string[] = FALLBACK_DEVICE_CATALOG.map((entry) => entry.device),
): BuildDocResult {
  let raw: unknown
  try {
    raw = parse(definition)
  } catch (err) {
    return {
      ok: false,
      reasons: [`not valid YAML: ${err instanceof Error ? err.message : String(err)}`],
    }
  }
  if (!isRecord(raw)) return { ok: false, reasons: ['the definition is not a YAML mapping'] }

  const reasons: string[] = []
  const doc: BuildDoc = { modules: [], vrfs: [], groups: [], extras: {}, nodes: [], links: [] }

  for (const [key, value] of Object.entries(raw)) {
    switch (key) {
      case 'name':
        if (typeof value === 'string') doc.name = value
        else doc.extras[key] = value
        break
      case 'provider':
        if (typeof value === 'string') doc.provider = value
        else doc.extras[key] = value
        break
      case 'defaults.device':
        doc.defaultDevice = parseDevice(value, 'default', reasons, knownDevices)
        if (doc.defaultDevice === undefined && typeof value !== 'string') doc.extras[key] = value
        break
      case 'defaults':
        if (isRecord(value)) {
          // Split: the device (typed, policy-gated) from the rest (extras).
          // Emit writes the typed half as dotted `defaults.device`, which
          // netlab merges back into the mapping — the split round-trips.
          const rest: Extras = {}
          for (const [defKey, defValue] of Object.entries(value)) {
            if (defKey === 'device') {
              doc.defaultDevice = parseDevice(defValue, 'default', reasons, knownDevices)
              if (doc.defaultDevice === undefined && typeof defValue !== 'string') {
                rest[defKey] = defValue
              }
            } else {
              rest[defKey] = defValue
            }
          }
          if (Object.keys(rest).length > 0) doc.extras[key] = rest
        } else {
          doc.extras[key] = value
        }
        break
      case 'module': {
        const modules = modulesShape(value)
        if (modules !== null) doc.modules = modules
        else doc.extras[key] = value
        break
      }
      case 'bgp.as':
        if (typeof value === 'number') doc.bgpAs = value
        else doc.extras[key] = value
        break
      case 'bgp': {
        const as = bgpShape(value)
        if (as !== null) doc.bgpAs = as
        else doc.extras[key] = value
        break
      }
      case 'mpls.ldp':
        if (typeof value === 'boolean') doc.mplsLdp = value
        else doc.extras[key] = value
        break
      case 'mpls': {
        const ldp = mplsBoolShape(value, 'ldp')
        if (ldp !== null) doc.mplsLdp = ldp
        else doc.extras[key] = value
        break
      }
      case 'vrfs': {
        const vrfs = vrfListShape(value)
        if (vrfs !== null) doc.vrfs = vrfs
        else doc.extras[key] = value
        break
      }
      case 'groups':
        doc.groups = parseGroups(value, doc.extras)
        break
      case 'addressing': {
        const addressing = mgmtAddressingShape(value)
        if (addressing !== null) doc.addressing = addressing
        else doc.extras[key] = value
        break
      }
      case 'nodes':
      case 'links':
        break // handled below, in order (links need the declared node names)
      default:
        doc.extras[key] = value
    }
  }

  const rawNodes = raw['nodes']
  if (rawNodes === undefined) {
    // A bare document (fresh lab) is representable; emit blocks an empty save.
  } else if (Array.isArray(rawNodes)) {
    for (const entry of rawNodes) {
      if (typeof entry === 'string') doc.nodes.push(parseNode(entry, null, reasons, knownDevices))
      else reasons.push(`node list entry ${describe(entry)} is not a plain name`)
    }
  } else if (isRecord(rawNodes)) {
    for (const [name, attrs] of Object.entries(rawNodes)) {
      doc.nodes.push(parseNode(name, attrs, reasons, knownDevices))
    }
  } else {
    reasons.push('"nodes" must be a mapping or a list of names')
  }

  const declared = new Set(doc.nodes.map((node) => node.name))
  doc.links = parseLinks(raw['links'], declared, reasons)

  if (reasons.length > 0) return { ok: false, reasons }
  return { ok: true, doc }
}

// --------------------------------------------------------------------------
// Emit
// --------------------------------------------------------------------------

function nodeYaml(node: BuildNode): Record<string, unknown> | null {
  const out: Record<string, unknown> = {}
  if (node.device !== undefined) out['device'] = node.device
  if (node.image !== undefined) out['image'] = node.image
  if (node.modules !== undefined) out['module'] = [...node.modules]
  if (node.bgpAs !== undefined) out['bgp.as'] = node.bgpAs
  if (node.mplsVpn !== undefined) out['mpls.vpn'] = node.mplsVpn
  if (node.vrfs !== undefined && Object.keys(node.vrfs).length > 0) {
    out['vrfs'] = Object.fromEntries(
      Object.entries(node.vrfs).map(([name, attrs]) => [
        name,
        Object.keys(attrs).length > 0 ? { ...attrs } : null,
      ]),
    )
  }
  for (const [key, value] of Object.entries(node.extras ?? {})) out[key] = value
  return Object.keys(out).length > 0 ? out : null
}

function groupYaml(group: BuildGroup): Record<string, unknown> | null {
  const out: Record<string, unknown> = {}
  if (group.members.length > 0) out['members'] = [...group.members]
  if (group.config !== undefined) out['config'] = [...group.config]
  for (const [key, value] of Object.entries(group.extras ?? {})) out[key] = value
  return Object.keys(out).length > 0 ? out : null
}

/** The advanced editors refuse builder-owned keys, so a same-key collision
 * between an extras entry and a typed field can only arise through edge
 * paths — this guard turns any such state into a loud save blocker instead
 * of an emitted document with a duplicate key. */
function extrasCollisions(
  extras: Extras | undefined,
  written: ReadonlySet<string>,
  where: string,
  problems: string[],
): void {
  for (const key of Object.keys(extras ?? {})) {
    if (written.has(key)) {
      problems.push(
        `${where}: advanced property "${key}" duplicates a builder-managed key — remove one of them`,
      )
    }
  }
}

/** Canonical emission. Problems are SAVE BLOCKERS shown to the user — the
 * emitter never silently fixes a doc (a 2-member "LAN" is a p2p link, a
 * device is intentful and never defaulted, an undeclared group member would
 * be rejected by netlab anyway). */
export function emitBuildDoc(doc: BuildDoc): EmitResult {
  const problems: string[] = []
  if (doc.nodes.length === 0) problems.push('the lab has no nodes yet')
  const nodeNames = new Set(doc.nodes.map((node) => node.name))
  const vrfNames = new Set(declaredVrfs(doc))
  for (const node of doc.nodes) {
    if (node.device === undefined && doc.defaultDevice === undefined) {
      problems.push(`node "${node.name}" has no device and the lab has no default device`)
    }
    for (const vrf of Object.keys(node.vrfs ?? {})) {
      if (!vrfNames.has(vrf)) {
        problems.push(`node "${node.name}": vrf "${vrf}" is not declared under the top-level vrfs`)
      }
    }
  }
  for (const link of doc.links) {
    if (link.kind === 'lan' && link.members.length < 3) {
      problems.push(
        link.members.length < 2
          ? `LAN segment "${link.id}" needs at least three members — connect them or delete it`
          : `LAN segment "${link.id}" has two members, which is a point-to-point link — connect a third member or use a direct link`,
      )
    }
  }
  for (const group of doc.groups) {
    // `_auto_create: true` asks netlab to create the members itself, so the
    // declared-node rule doesn't apply to that group.
    if (group.extras?.['_auto_create'] === true) continue
    for (const member of group.members) {
      if (!nodeNames.has(member)) {
        problems.push(`group "${group.name}": member "${member}" is not a declared node`)
      }
    }
  }

  const written = new Set<string>(['nodes', 'links'])
  if (doc.name !== undefined) written.add('name')
  if (doc.provider !== undefined) written.add('provider')
  if (doc.defaultDevice !== undefined) written.add('defaults.device')
  if (doc.modules.length > 0) written.add('module')
  if (doc.bgpAs !== undefined) written.add('bgp.as')
  if (doc.mplsLdp !== undefined) written.add('mpls.ldp')
  if (doc.vrfs.length > 0) written.add('vrfs')
  if (doc.groups.length > 0) written.add('groups')
  if (doc.addressing !== undefined) written.add('addressing')
  extrasCollisions(doc.extras, written, 'lab', problems)
  for (const node of doc.nodes) {
    const nodeWritten = new Set<string>()
    if (node.device !== undefined) nodeWritten.add('device')
    if (node.image !== undefined) nodeWritten.add('image')
    if (node.modules !== undefined) nodeWritten.add('module')
    if (node.bgpAs !== undefined) nodeWritten.add('bgp.as')
    if (node.mplsVpn !== undefined) nodeWritten.add('mpls.vpn')
    if (node.vrfs !== undefined && Object.keys(node.vrfs).length > 0) nodeWritten.add('vrfs')
    extrasCollisions(node.extras, nodeWritten, `node "${node.name}"`, problems)
  }
  for (const group of doc.groups) {
    const groupWritten = new Set<string>()
    if (group.members.length > 0) groupWritten.add('members')
    if (group.config !== undefined) groupWritten.add('config')
    extrasCollisions(group.extras, groupWritten, `group "${group.name}"`, problems)
  }
  if (problems.length > 0) return { ok: false, problems }

  const out: Record<string, unknown> = {}
  if (doc.name !== undefined) out['name'] = doc.name
  if (doc.provider !== undefined) out['provider'] = doc.provider
  if (doc.defaultDevice !== undefined) out['defaults.device'] = doc.defaultDevice
  if (doc.modules.length > 0) out['module'] = [...doc.modules]
  if (doc.bgpAs !== undefined) out['bgp.as'] = doc.bgpAs
  if (doc.mplsLdp !== undefined) out['mpls.ldp'] = doc.mplsLdp
  if (doc.vrfs.length > 0) {
    out['vrfs'] = Object.fromEntries(doc.vrfs.map((name) => [name, null]))
  }
  if (doc.groups.length > 0) {
    out['groups'] = Object.fromEntries(doc.groups.map((group) => [group.name, groupYaml(group)]))
  }
  if (doc.addressing !== undefined) {
    out['addressing'] = { mgmt: { ...doc.addressing.mgmt } }
  }
  for (const [key, value] of Object.entries(doc.extras)) out[key] = value
  out['nodes'] = Object.fromEntries(doc.nodes.map((node) => [node.name, nodeYaml(node)]))
  out['links'] = doc.links.map((link) =>
    link.kind === 'p2p' ? `${link.a}-${link.b}` : [...link.members],
  )
  return { ok: true, yaml: stringify(out) }
}

export function emptyBuildDoc(): BuildDoc {
  // provider clab: the only provider this deployment deploys through.
  return { provider: 'clab', modules: [], vrfs: [], groups: [], extras: {}, nodes: [], links: [] }
}

/** First free auto-name for a palette-added node: vyos1, vyos2, … */
export function nextNodeName(doc: BuildDoc, device: string): string {
  const taken = new Set(doc.nodes.map((node) => node.name))
  for (let i = 1; ; i += 1) {
    const name = `${device}${i}`
    if (!taken.has(name)) return name
  }
}

export function nextLanId(doc: BuildDoc): string {
  let max = 0
  for (const link of doc.links) {
    if (link.kind === 'lan') {
      const n = Number(link.id.slice('lan:'.length))
      if (Number.isInteger(n) && n > max) max = n
    }
  }
  return `lan:${max + 1}`
}

/** Deep key-sort for extras comparison: YAML mappings that differ only in key
 * order are the same document. */
function sortedDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortedDeep)
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, sortedDeep(value[key])]),
    )
  }
  return value
}

function canonicalExtras(extras: Extras | undefined): unknown {
  return extras !== undefined && Object.keys(extras).length > 0 ? sortedDeep(extras) : null
}

function canonical(doc: BuildDoc): unknown {
  return {
    name: doc.name ?? null,
    provider: doc.provider ?? null,
    defaultDevice: doc.defaultDevice ?? null,
    modules: doc.modules,
    bgpAs: doc.bgpAs ?? null,
    mplsLdp: doc.mplsLdp ?? null,
    vrfs: [...doc.vrfs].sort(),
    groups: doc.groups.map((group) => ({
      name: group.name,
      members: group.members,
      config: group.config ?? null,
      extras: canonicalExtras(group.extras),
    })),
    addressing: doc.addressing ?? null,
    extras: canonicalExtras(doc.extras),
    nodes: doc.nodes.map((node) => ({
      name: node.name,
      device: node.device ?? null,
      image: node.image ?? null,
      modules: node.modules ?? null,
      bgpAs: node.bgpAs ?? null,
      mplsVpn: node.mplsVpn ?? null,
      vrfs:
        node.vrfs !== undefined && Object.keys(node.vrfs).length > 0
          ? Object.entries(node.vrfs)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([name, attrs]) => ({ name, loopback: attrs.loopback ?? null }))
          : null,
      extras: canonicalExtras(node.extras),
    })),
    links: doc.links.map((link) =>
      link.kind === 'p2p'
        ? { kind: 'p2p', a: link.a, b: link.b }
        : { kind: 'lan', members: link.members },
    ),
  }
}

/** Round-trip equality, ignoring LAN ids (session metadata reassigned on
 * every parse), empty-vs-absent vrf membership records, and extras key
 * order. */
export function buildDocEquals(a: BuildDoc, b: BuildDoc): boolean {
  return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b))
}
