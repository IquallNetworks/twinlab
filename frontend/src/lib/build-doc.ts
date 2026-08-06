import { parse, stringify } from 'yaml'

import { BUILDER_MODULES, FALLBACK_DEVICE_CATALOG, type BuilderModule } from './device-catalog'

// The builder's document model: a typed core the visual controls edit, plus
// LOSSLESS `extras` passthrough at the lab, node and group level. Every key of
// a definition lives in exactly ONE of the two — the typed model when it has
// the exact shape a control can edit, `extras` (preserved verbatim, edited as
// YAML in the inspector's advanced sections) otherwise. parseBuildDoc gates
// only on what netlab itself rejects, plus the unknown-device POLICY gate;
// unknown or overflow DATA never gates and is never dropped. Where netlab
// accepts several spellings of one thing, all of them parse and emission
// picks one — so a save can REWRITE a document (a link group comes back
// expanded), which parse reports as a notice.
//
// Typed core: nodes (mapping or either list form) + links (stub/p2p/LAN by
// endpoint count, with a typed name and lossless link-level + per-endpoint
// extras — the string, list, dict, and interfaces forms all parse, list
// members may be records, an endpoint may repeat (a self-link), and the
// dict-of-lists form keeps its list names; dict and interfaces are equivalent
// in netlab's expansion), groups (members + config templates), netlab's whole
// module vocabulary (presence for all of them; bgp.as, mpls.ldp, mpls.vpn and
// vrf membership are the ones with controls of their own — every other
// module's attributes ride the extras), the curated device catalog, and the
// keys the backend itself
// injects on save (name, addressing.mgmt). Emission is canonical; the
// round-trip invariant is: for any doc emitBuildDoc accepts,
// parseBuildDoc(emit(doc)) equals doc (up to LAN/stub ids, which are session
// metadata).
//
// Pure module (no React, no `@/` alias imports) so a plain node script can
// exercise the round-trip.

export { BUILDER_MODULES, type BuilderModule } from './device-catalog'

export type Extras = Record<string, unknown>

export interface BuildNodeVrf {
  loopback?: boolean
  // Everything else this node says about the vrf, verbatim.
  extras?: Extras
}

/** A top-level vrf declaration: the name is typed, its attributes (rd, rt,
 * import/export, …) ride alongside it. They live TOGETHER rather than the
 * name being typed and the attributes landing in doc.extras, so a vrf can
 * never exist in one half and not the other. */
export interface BuildDocVrf {
  name: string
  extras?: Extras
}

/** A node's loopback addressing. The `{pool: …}` and boolean spellings are
 * not typed — a value that is not a mapping rides the node extras whole. */
export interface BuildNodeLoopback {
  ipv4?: string
  ipv6?: string
  extras?: Extras
}

// netlab's node roles. `router` is the default and the only one that gets a
// loopback interface (augment/nodes.py:224); the allowed set is per-device,
// which the dry create judges.
export const NODE_ROLES = ['router', 'host', 'bridge', 'gateway'] as const
export type NodeRole = (typeof NODE_ROLES)[number]

export interface BuildNode {
  name: string
  device?: string
  // The container image. netlab spells this `box` OR `image` and `box` WINS
  // (augment/nodes.py:335 returns early on box, before moving image into it),
  // so both are ONE field here — typing only `image` left a document setting
  // `box:` showing an empty, editable Image control that decided nothing.
  image?: string
  // Which spelling the document used, so a save does not rewrite it. Absent
  // means `image`.
  imageKey?: 'box'
  role?: NodeRole
  // undefined → the node inherits the global module list; [] → explicitly none.
  modules?: BuilderModule[]
  bgpAs?: number
  mplsVpn?: boolean
  vrfs?: Record<string, BuildNodeVrf>
  loopback?: BuildNodeLoopback
  // Custom-config templates attached to this node (netlab `config: [...]`),
  // the same list a group broadcasts to its members. Config import writes one
  // per node: the carry template.
  config?: string[]
  // Attributes outside the typed set, preserved verbatim.
  extras?: Extras
}

function loopbackShape(value: unknown): BuildNodeLoopback | null {
  if (!isRecord(value)) return null
  const loopback: BuildNodeLoopback = {}
  const extras: Extras = {}
  for (const [key, entry] of Object.entries(value)) {
    if ((key === 'ipv4' || key === 'ipv6') && typeof entry === 'string') loopback[key] = entry
    else extras[key] = entry
  }
  if (Object.keys(extras).length > 0) loopback.extras = extras
  return loopback
}

function loopbackYaml(loopback: BuildNodeLoopback): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (loopback.ipv4 !== undefined) out['ipv4'] = loopback.ipv4
  if (loopback.ipv6 !== undefined) out['ipv6'] = loopback.ipv6
  for (const [key, value] of Object.entries(loopback.extras ?? {})) out[key] = value
  return out
}

export interface BuildGroup {
  name: string
  members: string[]
  // Custom-config templates attached to the members (netlab `config: [...]`).
  config?: string[]
  // Everything else a group broadcasts (module, bgp.as, _auto_create, …).
  extras?: Extras
}

export interface LinkEndpoint {
  node: string
  // This end's interface name on the NOS side. Imported labs carry it for
  // interface-name fidelity; netlab derives it otherwise.
  ifname?: string
  // This end's address. `false` says "no address here" — netlab INVENTS one
  // for a bare endpoint on an addressed link (live-proven, delta 23), so the
  // spelling matters.
  ipv4?: string | false
  ipv6?: string | false
  // Everything else this end carries (ospf.cost, vlan.access, …), preserved
  // verbatim — the dict form's node-key value, or an interfaces-form record
  // minus its `node`. Dict and interfaces forms expand identically in netlab
  // (verified against netlab create 2026-08-04), so both parse here and emit
  // canonical.
  extras?: Extras
}

/** Split one endpoint's attributes into the typed fields and the rest — the
 * single rule the dict form, the interfaces form and list members share. */
function parseEndpoint(node: string, attrs: Extras): LinkEndpoint {
  const endpoint: LinkEndpoint = { node }
  const extras: Extras = {}
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'ifname' && typeof value === 'string') endpoint.ifname = value
    else if ((key === 'ipv4' || key === 'ipv6') && (typeof value === 'string' || value === false)) {
      endpoint[key] = value
    } else extras[key] = value
  }
  if (Object.keys(extras).length > 0) endpoint.extras = extras
  return endpoint
}

/** An endpoint's attributes as YAML: typed fields first, then the rest. */
function endpointAttrsYaml(endpoint: LinkEndpoint): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (endpoint.ifname !== undefined) out['ifname'] = endpoint.ifname
  if (endpoint.ipv4 !== undefined) out['ipv4'] = endpoint.ipv4
  if (endpoint.ipv6 !== undefined) out['ipv6'] = endpoint.ipv6
  for (const [key, value] of Object.entries(endpoint.extras ?? {})) out[key] = value
  return out
}

/** The link-level attributes every kind carries. */
export interface LinkAttrs {
  // A label the canvas shows.
  name?: string
  // netlab's link prefix: a CIDR, the name of a declared prefix pool, or
  // `false` for an L2 wire with no addressing (what config import emits for
  // an all-unaddressed link, and what a self-link needs). The dict spelling
  // (`{ipv4, ipv6, allocation}`) rides the extras.
  prefix?: string | false
  bandwidth?: number
  mtu?: number
  // Any other link attribute, verbatim.
  extras?: Extras
  // The key of the named sub-list a link came from, when `links:` was written
  // as netlab's dict-of-lists. netlab flattens those lists (the name only ever
  // reaches error messages), so it is pure organization — carried here so a
  // save re-emits the author's grouping instead of flattening it.
  listName?: string
}

// Endpoint COUNT decides the kind (netlab's `type` is derived, not authored):
// 1 → stub, 2 → p2p, 3+ → LAN.
export type BuildLink =
  // Bare (no attributes anywhere) emits as the terse "a-b" string form
  // (safe: no hyphen in either endpoint name); attributed links emit dict form.
  | ({ kind: 'p2p'; a: LinkEndpoint; b: LinkEndpoint } & LinkAttrs)
  // 3+ endpoints, emitted as a member list when bare. Ids are `lan:<n>` in
  // document order — the SAME scheme as lib/topology.ts, so manual canvas
  // layouts keyed by these ids carry across the Topology and Build tabs.
  | ({ kind: 'lan'; id: string; members: LinkEndpoint[] } & LinkAttrs)
  // One endpoint — netlab resolves it to a loopback/stub interface. Always
  // emits dict form (`- <node>:`). Ids are `stub:<n>`, session metadata like
  // LAN ids.
  | ({ kind: 'stub'; id: string; endpoint: LinkEndpoint } & LinkAttrs)

/** The endpoints of any link kind, in document order. */
export function linkEndpoints(link: BuildLink): LinkEndpoint[] {
  switch (link.kind) {
    case 'p2p':
      return [link.a, link.b]
    case 'lan':
      return link.members
    case 'stub':
      return [link.endpoint]
  }
}

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
  vrfs: BuildDocVrf[]
  // Keys under `groups:` that are not groups at all (netlab reads a
  // groups-level `_auto_create`), kept verbatim so one of them can no longer
  // send every group into extras and empty the Groups UI.
  groupsExtras?: Extras
  groups: BuildGroup[]
  // Injected by the backend on save (the lab's allocated mgmt subnet);
  // preserved verbatim.
  addressing?: MgmtAddressing
  // Top-level keys outside the typed core, preserved verbatim.
  extras: Extras
  nodes: BuildNode[]
  links: BuildLink[]
}

// `notices` report a representable-but-REWRITTEN form: the doc is fine to
// edit, saving just won't spell it the way it was authored (link groups
// expand). Reasons gate; notices only inform.
export type BuildDocResult =
  | { ok: true; doc: BuildDoc; notices: string[] }
  | { ok: false; reasons: string[] }
export type EmitResult = { ok: true; yaml: string } | { ok: false; problems: string[] }

// As-you-type rule for NEW names in the builder: lowercase keeps emitted
// definitions uniform, and no hyphen keeps the terse "a-b" link form
// available (netlab splits that form on '-', so a hyphenated name can only be
// spelled in the list/dict/interfaces forms).
export const NODE_NAME_RE = /^[a-z_][a-z0-9_]*$/
// netlab's own id rule caps names at 16 characters (data/types.py).
export const NODE_NAME_MAX = 16

// Existing hand-written definitions get netlab's full id rule: uppercase and
// hyphens round-trip fine, only the structural constraints matter.
const EXISTING_NAME_RE = /^[A-Za-z_][A-Za-z0-9_-]*$/

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

/** A module mapping split into the ONE subkey a control owns and everything
 * else, verbatim. The whole-key alternative — demoting `bgp: {as, router_id}`
 * to extras including the `as` — hid a typed value behind an unrelated
 * sibling; this is the same per-object partition the fact namespace settled
 * on (delta 26). `rest` is undefined when nothing else was there, so the
 * common case still emits the terse dotted key. */
interface SubkeySplit<T> {
  typed: T | undefined
  rest: Extras | undefined
}

function splitModuleKey<T>(
  value: unknown,
  subkey: string,
  typedShape: (raw: unknown) => T | null,
): SubkeySplit<T> | null {
  if (!isRecord(value)) return null
  const rest: Extras = {}
  let typed: T | undefined
  for (const [key, entry] of Object.entries(value)) {
    const shaped = key === subkey ? typedShape(entry) : null
    if (shaped !== null) typed = shaped
    else rest[key] = entry
  }
  return { typed, rest: Object.keys(rest).length > 0 ? rest : undefined }
}

const numberShape = (value: unknown): number | null => (typeof value === 'number' ? value : null)
const boolShape = (value: unknown): boolean | null => (typeof value === 'boolean' ? value : null)

/** The `as` a `bgp:` mapping carries, when it carries one in the typed shape.
 * Used by the advanced editors; the parser uses the full split. */
function bgpShape(value: unknown): number | null {
  return splitModuleKey(value, 'as', numberShape)?.typed ?? null
}

function mplsBoolShape(value: unknown, key: 'ldp' | 'vpn'): boolean | null {
  return splitModuleKey(value, key, boolShape)?.typed ?? null
}

/** Merge a typed subkey back into the extras half for emission. With nothing
 * else to carry, the terse dotted spelling wins (`bgp.as: 65000`); otherwise
 * both halves emit as ONE mapping, which is what netlab would have made of
 * the dotted key anyway. */
function moduleKeyYaml(
  out: Record<string, unknown>,
  key: 'bgp' | 'mpls',
  subkey: string,
  typed: unknown,
  rest: Extras | undefined,
): void {
  if (rest === undefined) {
    if (typed !== undefined) out[`${key}.${subkey}`] = typed
    return
  }
  out[key] = typed === undefined ? { ...rest } : { [subkey]: typed, ...rest }
}

/** Top-level vrfs: a mapping of declarations, each name typed and its
 * attributes (rd, rt, …) carried beside it. A vrf whose value is neither a
 * mapping nor empty keeps that value in its extras — netlab will judge it. */
function vrfListShape(value: unknown): BuildDocVrf[] | null {
  if (!isRecord(value)) return null
  const vrfs: BuildDocVrf[] = []
  for (const [name, attrs] of Object.entries(value)) {
    if (!EXISTING_NAME_RE.test(name) || name.length > NODE_NAME_MAX) return null
    if (attrs === null || (isRecord(attrs) && Object.keys(attrs).length === 0)) {
      vrfs.push({ name })
    } else if (isRecord(attrs)) {
      vrfs.push({ name, extras: attrs })
    } else {
      vrfs.push({ name, extras: { [VRF_SCALAR_KEY]: attrs } })
    }
  }
  return vrfs
}

// A vrf declared with a scalar value (`vpn_a: 5`) is not a shape netlab
// accepts, but the builder still must not lose it: it round-trips under this
// private key and emits back as the bare scalar.
const VRF_SCALAR_KEY = '__scalar__'

function vrfYaml(vrf: BuildDocVrf): unknown {
  if (vrf.extras === undefined) return null
  if (VRF_SCALAR_KEY in vrf.extras) return vrf.extras[VRF_SCALAR_KEY]
  return { ...vrf.extras }
}

/** Node vrf membership: `loopback` is typed, anything else the node says
 * about the vrf rides its extras. Declaration against the top-level vrfs is
 * checked at emit (a save blocker), not here — shape and reference are
 * different rules. */
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
    const extras: Extras = {}
    for (const [key, attr] of Object.entries(attrs)) {
      if (key === 'loopback' && typeof attr === 'boolean') entry.loopback = attr
      else extras[key] = attr
    }
    if (Object.keys(extras).length > 0) entry.extras = extras
    vrfs[vrfName] = entry
  }
  return vrfs
}

function nodeVrfYaml(attrs: BuildNodeVrf): unknown {
  const out: Record<string, unknown> = {}
  if (attrs.loopback !== undefined) out['loopback'] = attrs.loopback
  for (const [key, value] of Object.entries(attrs.extras ?? {})) out[key] = value
  return Object.keys(out).length > 0 ? out : null
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
      // The mapping itself is fine here — only the subkey a control owns is
      // not, since emission merges the two halves into one `bgp:`.
      return bgpShape(value) !== null ? 'the "as" subkey belongs to the BGP AS control' : null
    case 'mpls.ldp':
      return typeof value === 'boolean' ? 'use the LDP transport control' : null
    case 'mpls':
      return mplsBoolShape(value, 'ldp') !== null
        ? 'the "ldp" subkey belongs to the LDP transport control'
        : null
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
    case 'box':
      // One setting, two spellings — the control owns both.
      return typeof value === 'string' ? 'use the Image override control' : null
    case 'role':
      return typeof value === 'string' && (NODE_ROLES as readonly string[]).includes(value)
        ? 'use the Role control'
        : null
    case 'group':
      return stringListShape(value) !== null
        ? 'group membership is edited on the group'
        : null
    case 'module':
      return modulesShape(value) !== null ? 'use the Modules control' : null
    case 'bgp.as':
      return typeof value === 'number' ? 'use the BGP AS control' : null
    case 'bgp':
      return bgpShape(value) !== null ? 'the "as" subkey belongs to the BGP AS control' : null
    case 'mpls.vpn':
      return typeof value === 'boolean' ? 'use the MPLS VPN edge control' : null
    case 'mpls':
      return mplsBoolShape(value, 'vpn') !== null
        ? 'the "vpn" subkey belongs to the MPLS VPN edge control'
        : null
    case 'vrfs':
      return nodeVrfsShape(value) !== null ? 'use the VRF membership controls' : null
    case 'loopback':
      return isRecord(value) ? 'use the Loopback fields' : null
    case 'config':
      return stringListShape(value) !== null ? 'use the template picker' : null
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

/** The names a link entry's keys may name as endpoints — netlab's
 * is_nodename_valid: a declared node, or `<node>_<member>` where that node
 * pulls in a `components:` entry with `include:` (the component expansion
 * creates those nodes long after this parse runs, so the prefix is all either
 * side can check). */
export interface DeclaredNodes {
  has(name: string): boolean
}

export function declaredNodes(nodes: readonly BuildNode[]): DeclaredNodes {
  const names = new Set(nodes.map((node) => node.name))
  const prefixes = nodes
    .filter((node) => node.extras?.['include'] !== undefined)
    .map((node) => `${node.name}_`)
  return {
    has: (name) => names.has(name) || prefixes.some((prefix) => name.startsWith(prefix)),
  }
}

/** Advanced-editor validation, link level. A key naming ANY declared node
 * would re-parse as an endpoint (the dict form's discrimination rule), so it
 * can never ride the extras — not even a node absent from this link. */
export function linkExtrasKeyError(
  key: string,
  value: unknown,
  declaredNodes: DeclaredNodes,
): string | null {
  if (declaredNodes.has(key)) return `"${key}" is a declared node — endpoints are edited on the canvas`
  if (key === 'name' && typeof value === 'string') return 'use the Name field'
  if (key === 'interfaces') return 'endpoint lists are managed by the builder'
  if (key === 'prefix' && (typeof value === 'string' || value === false)) {
    return 'use the Prefix field'
  }
  if (key === 'bandwidth' && typeof value === 'number') return 'use the Bandwidth field'
  if (key === 'mtu' && typeof value === 'number') return 'use the MTU field'
  return null
}

/** The vrf names a node may reference: the typed declarations plus — when
 * `vrfs:` was not a mapping at all and rode into extras whole — the names
 * declared there. */
export function declaredVrfs(doc: BuildDoc): string[] {
  const fromExtras = doc.extras['vrfs']
  return [
    ...doc.vrfs.map((vrf) => vrf.name),
    ...(isRecord(fromExtras) ? Object.keys(fromExtras) : []),
  ]
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
  // Collects node-side `group:` declarations, which parseBuildDoc folds into
  // the groups' member lists (netlab's own add_node_level_groups does exactly
  // that). Absent for a standalone node fragment, which has no document to
  // fold them into — there the key stays a verbatim extra.
  memberships?: { node: string; group: string }[],
): BuildNode {
  const node: BuildNode = { name }
  if (!EXISTING_NAME_RE.test(name) || name.length > NODE_NAME_MAX) {
    reasons.push(
      `node name "${name}" is outside netlab's rules (letters, digits, underscores, hyphens; max ${NODE_NAME_MAX})`,
    )
  }
  if (attrs === null || attrs === undefined) return node
  if (!isRecord(attrs)) {
    reasons.push(`node "${name}" must be empty or a mapping of attributes`)
    return node
  }
  const extras: Extras = {}
  // Resolved together after the loop — they are one setting with two
  // spellings, and which one wins does not depend on document order.
  let rawBox: unknown
  let rawImage: unknown
  for (const [key, value] of Object.entries(attrs)) {
    switch (key) {
      case 'device': {
        const device = parseDevice(value, `node "${name}":`, reasons, knownDevices)
        if (device !== undefined) node.device = device
        else if (typeof value !== 'string') extras[key] = value
        break
      }
      case 'image':
        rawImage = value
        break
      case 'box':
        rawBox = value
        break
      case 'role':
        if (typeof value === 'string' && (NODE_ROLES as readonly string[]).includes(value)) {
          node.role = value as NodeRole
        } else extras[key] = value
        break
      case 'group': {
        const groups = memberships === undefined ? null : stringListShape(value)
        if (groups === null) extras[key] = value
        else for (const group of groups) memberships?.push({ node: name, group })
        break
      }
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
        const split = splitModuleKey(value, 'as', numberShape)
        if (split === null) extras[key] = value
        else {
          if (split.typed !== undefined) node.bgpAs = split.typed
          if (split.rest !== undefined) extras[key] = split.rest
        }
        break
      }
      case 'mpls.vpn':
        if (typeof value === 'boolean') node.mplsVpn = value
        else extras[key] = value
        break
      case 'mpls': {
        const split = splitModuleKey(value, 'vpn', boolShape)
        if (split === null) extras[key] = value
        else {
          if (split.typed !== undefined) node.mplsVpn = split.typed
          if (split.rest !== undefined) extras[key] = split.rest
        }
        break
      }
      case 'vrfs': {
        const vrfs = nodeVrfsShape(value)
        if (vrfs !== null) node.vrfs = vrfs
        else extras[key] = value
        break
      }
      case 'loopback': {
        const loopback = loopbackShape(value)
        if (loopback !== null) node.loopback = loopback
        else extras[key] = value
        break
      }
      case 'config': {
        const config = stringListShape(value)
        if (config !== null) node.config = config
        else extras[key] = value
        break
      }
      default:
        extras[key] = value
    }
  }
  // `box` wins over `image` in netlab, which then DELETES the image key —
  // keep the loser verbatim so nothing is lost, and remember the spelling.
  if (typeof rawBox === 'string') {
    node.image = rawBox
    node.imageKey = 'box'
    if (rawImage !== undefined) extras['image'] = rawImage
  } else {
    if (rawBox !== undefined) extras['box'] = rawBox
    if (typeof rawImage === 'string') node.image = rawImage
    else if (rawImage !== undefined) extras['image'] = rawImage
  }
  if (Object.keys(extras).length > 0) node.extras = extras
  return node
}

export type NodeFragmentResult =
  | { ok: true; node: BuildNode & { device: string } }
  | { ok: false; reason: string }

/** Parse a node-template fragment (a YAML mapping of node attributes, no node
 * name — delta 21) through the same typed-vs-extras split parseBuildDoc
 * applies to a node, so a stamped node is indistinguishable from a
 * hand-authored one. The fragment must name a cataloged device — the same
 * POLICY gate the parser applies (an uncataloged device is text-editor
 * territory). `name` is the node name the stamp will use. */
export function parseNodeFragment(
  fragment: string,
  name: string,
  knownDevices: readonly string[],
): NodeFragmentResult {
  let raw: unknown
  try {
    raw = parse(fragment)
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return { ok: false, reason: `not valid YAML: ${message}` }
  }
  if (!isRecord(raw)) {
    return { ok: false, reason: 'a node template must be a mapping of node attributes' }
  }
  const reasons: string[] = []
  const node = parseNode(name, raw, reasons, knownDevices)
  const reason = reasons[0]
  if (reason !== undefined) return { ok: false, reason }
  const device = node.device
  if (device === undefined) return { ok: false, reason: 'the template names no device' }
  return { ok: true, node: { ...node, device } }
}

/** A node's attributes as a template fragment — the node minus its name
 * (re-chosen at stamp time). Null when the node carries nothing to save. */
export function emitNodeFragment(node: BuildNode): string | null {
  const out = nodeYaml(node)
  return out === null ? null : stringify(out)
}

/** Groups parse per-group: members/config in their exact shapes are typed,
 * every other key rides that group's extras. A groups mapping whose VALUES
 * are not all mappings (e.g. a `_auto_create: true` toggle at the groups
 * level) is preserved whole in the doc extras instead. */
function parseGroups(value: unknown, doc: BuildDoc): BuildGroup[] {
  if (!isRecord(value)) {
    doc.extras['groups'] = value
    return []
  }
  const groups: BuildGroup[] = []
  const groupsExtras: Extras = {}
  for (const [name, attrs] of Object.entries(value)) {
    // netlab reads a groups-level `_auto_create` beside the groups
    // themselves. Only a mapping (or an empty group) is a group; anything
    // else is a setting, and it used to take every group with it.
    if (attrs !== null && !isRecord(attrs)) {
      groupsExtras[name] = attrs
      continue
    }
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
  if (Object.keys(groupsExtras).length > 0) doc.groupsExtras = groupsExtras
  return groups
}

interface ParsedLinkEntry {
  // Where this entry sits, for messages — a group member's is not its index
  // in the enclosing list.
  where: string
  endpoints: LinkEndpoint[]
  attrs: LinkAttrs
}

/** Split ONE link-level key into the typed attributes or the extras — the
 * single rule the dict form, the interfaces form and link groups all use, so
 * a key can never be typed in one spelling and extras in another. */
function takeLinkAttr(attrs: LinkAttrs, extras: Extras, key: string, value: unknown): void {
  if (key === 'name' && typeof value === 'string') attrs.name = value
  else if (key === 'prefix' && (typeof value === 'string' || value === false)) attrs.prefix = value
  else if (key === 'bandwidth' && typeof value === 'number') attrs.bandwidth = value
  else if (key === 'mtu' && typeof value === 'number') attrs.mtu = value
  else extras[key] = value
}

/** One link entry in any accepted form. String "a-b" and list forms carry
 * bare endpoints; the dict form splits node keys (endpoints, their value the
 * per-endpoint extras) from `name` and the link extras; the interfaces form
 * reads its records the same way. Gated: link groups and attribute-only
 * entries (no endpoints), a node listed twice, scalar endpoint values. */
function parseLinkEntry(entry: unknown, where: string, declared: DeclaredNodes, reasons: string[]): ParsedLinkEntry | null {
  if (typeof entry === 'string') {
    const parts = entry.split('-').filter((part) => part !== '')
    if (parts.length < 2) {
      reasons.push(`${where} ("${entry}") is not an "a-b" endpoint pair`)
      return null
    }
    return { where, endpoints: parts.map((node) => ({ node })), attrs: {} }
  }
  if (Array.isArray(entry)) {
    // netlab's adjust_interface_list: a member is a bare node name or an
    // interfaces-form record — the same {node, …} shape, mixable in one list.
    const endpoints: LinkEndpoint[] = []
    for (const member of entry) {
      if (typeof member === 'string') {
        endpoints.push({ node: member })
      } else if (isRecord(member) && typeof member['node'] === 'string') {
        const { node, ...rest } = member as { node: string } & Extras
        endpoints.push(parseEndpoint(node, rest))
      } else {
        reasons.push(`${where}: every list member is a node name or a {node, …} record`)
        return null
      }
    }
    if (endpoints.length < 1) {
      reasons.push(`${where} is an empty endpoint list`)
      return null
    }
    return { where, endpoints, attrs: {} }
  }
  if (!isRecord(entry)) {
    reasons.push(`${where} (${describe(entry)}) is not a link form the builder knows`)
    return null
  }

  const parsed: ParsedLinkEntry = { where, endpoints: [], attrs: {} }
  const extras: Extras = {}
  const rawInterfaces = entry['interfaces']
  if (rawInterfaces !== undefined) {
    // interfaces form: the endpoint list lives under `interfaces`, every
    // sibling key is a link attribute. Emit re-spells it as the equivalent
    // dict form (proven identical in netlab's expansion).
    if (!Array.isArray(rawInterfaces)) {
      reasons.push(`${where}: "interfaces" must be a list of {node, …} records`)
      return null
    }
    for (const record of rawInterfaces) {
      if (!isRecord(record) || typeof record['node'] !== 'string') {
        reasons.push(`${where}: every interfaces record needs a "node" name`)
        return null
      }
      const { node, ...rest } = record as { node: string } & Extras
      parsed.endpoints.push(parseEndpoint(node, rest))
    }
    for (const [key, value] of Object.entries(entry)) {
      if (key === 'interfaces') continue
      if (declared.has(key)) {
        reasons.push(`${where} mixes the interfaces form with node keys`)
        return null
      }
      takeLinkAttr(parsed.attrs, extras, key, value)
    }
  } else {
    // dict form: keys in the declared-node set are endpoints (netlab's own
    // discrimination rule), everything else is `name` or a link attribute.
    for (const [key, value] of Object.entries(entry)) {
      if (declared.has(key)) {
        if (value === null || value === undefined) parsed.endpoints.push({ node: key })
        else if (isRecord(value)) parsed.endpoints.push(parseEndpoint(key, value))
        else {
          reasons.push(`${where}: endpoint "${key}" must be empty or a mapping of attributes`)
          return null
        }
      } else {
        takeLinkAttr(parsed.attrs, extras, key, value)
      }
    }
  }
  if (parsed.endpoints.length === 0) {
    reasons.push(
      `${where} has no declared node as an endpoint (link groups and attribute-only entries are text-editor territory)`,
    )
    return null
  }
  if (Object.keys(extras).length > 0) parsed.attrs.extras = extras
  return parsed
}

/** A link group (`group:` + `members:`) as netlab expands it: every member is
 * a link of its own carrying the group's attributes, which the member's own
 * attributes override (expand_groups copies the group data in first). The
 * expansion is what gets saved — the group spelling itself is not preserved,
 * which the caller reports as a notice. */
function expandLinkGroup(
  entry: Record<string, unknown>,
  where: string,
  declared: DeclaredNodes,
  reasons: string[],
  notices: string[],
): ParsedLinkEntry[] {
  const members = entry['members']
  if (!Array.isArray(members)) {
    reasons.push(`${where} is a link group with no "members" list`)
    return []
  }
  const groupAttrs: LinkAttrs = {}
  const groupExtras: Extras = {}
  for (const [key, value] of Object.entries(entry)) {
    if (key === 'group' || key === 'members') continue
    if (declared.has(key)) {
      // netlab would fold these into every member's interface list; the
      // builder has no way to show one endpoint shared by N links.
      reasons.push(`${where} is a link group that also declares "${key}" as an endpoint`)
      return []
    }
    takeLinkAttr(groupAttrs, groupExtras, key, value)
  }
  const expanded: ParsedLinkEntry[] = []
  members.forEach((member, index) => {
    const parsed = parseLinkEntry(member, `${where}.members[${index + 1}]`, declared, reasons)
    if (parsed === null) return
    // Group data first, the member's own data over it — netlab's order.
    const extras = { ...groupExtras, ...parsed.attrs.extras }
    expanded.push({
      where: parsed.where,
      endpoints: parsed.endpoints,
      attrs: {
        ...groupAttrs,
        ...parsed.attrs,
        ...(Object.keys(extras).length > 0 ? { extras } : { extras: undefined }),
      },
    })
  })
  if (expanded.length > 0) {
    notices.push(
      `${where} is a link group — the builder expands it into ${expanded.length} links, and saving stores them expanded`,
    )
  }
  return expanded
}

/** LAN/stub ids run across the whole document, not per named sub-list. */
interface LinkIds {
  lan: number
  stub: number
}

function parseLinkList(
  entries: readonly unknown[],
  declared: DeclaredNodes,
  reasons: string[],
  notices: string[],
  ids: LinkIds,
  label: (index: number) => string,
  listName: string | undefined,
): BuildLink[] {
  const links: BuildLink[] = []
  entries.forEach((entry, index) => {
    const at = label(index)
    // One entry is one link — except a link group, which is N.
    const parsedEntries = isRecord(entry) && 'group' in entry
      ? expandLinkGroup(entry, at, declared, reasons, notices)
      : [parseLinkEntry(entry, at, declared, reasons)]
    for (const parsed of parsedEntries) {
      if (parsed === null) continue
      const where = parsed.where
      const { endpoints } = parsed
      const undeclaredEndpoint = endpoints.find((endpoint) => !declared.has(endpoint.node))
      if (undeclaredEndpoint !== undefined) {
        reasons.push(`${where} references undeclared node "${undeclaredEndpoint.node}"`)
        continue
      }
      // Undefined-valued keys would survive into the doc and break the
      // round-trip comparison, so drop them rather than spreading blind.
      const shared: LinkAttrs = { ...(listName !== undefined && { listName }) }
      for (const [key, value] of Object.entries(parsed.attrs)) {
        if (value !== undefined) (shared as Record<string, unknown>)[key] = value
      }
      if (endpoints.length === 1) {
        ids.stub += 1
        links.push({ kind: 'stub', id: `stub:${ids.stub}`, endpoint: endpoints[0] as LinkEndpoint, ...shared })
      } else if (endpoints.length === 2) {
        const [a, b] = endpoints as [LinkEndpoint, LinkEndpoint]
        links.push({ kind: 'p2p', a, b, ...shared })
      } else {
        ids.lan += 1
        links.push({ kind: 'lan', id: `lan:${ids.lan}`, members: endpoints, ...shared })
      }
    }
  })
  return links
}

/** Both `links:` shapes netlab's adjust_link_list accepts: a list, or a
 * mapping of NAMED lists it flattens (the names survive here as `listName`,
 * so a save re-emits the grouping). */
function parseLinks(
  value: unknown,
  declared: DeclaredNodes,
  reasons: string[],
  notices: string[],
): BuildLink[] {
  if (value === undefined) return []
  const ids: LinkIds = { lan: 0, stub: 0 }
  if (Array.isArray(value)) {
    return parseLinkList(
      value,
      declared,
      reasons,
      notices,
      ids,
      (index) => `link ${index + 1}`,
      undefined,
    )
  }
  if (!isRecord(value)) {
    reasons.push('"links" must be a list or a mapping of named link lists')
    return []
  }
  const links: BuildLink[] = []
  for (const [listName, sublist] of Object.entries(value)) {
    if (!Array.isArray(sublist)) {
      reasons.push(`"links.${listName}" must be a list of links`)
      continue
    }
    links.push(
      ...parseLinkList(
        sublist,
        declared,
        reasons,
        notices,
        ids,
        (index) => `links.${listName}[${index + 1}]`,
        listName,
      ),
    )
  }
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
  const notices: string[] = []
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
        const split = splitModuleKey(value, 'as', numberShape)
        if (split === null) doc.extras[key] = value
        else {
          if (split.typed !== undefined) doc.bgpAs = split.typed
          if (split.rest !== undefined) doc.extras[key] = split.rest
        }
        break
      }
      case 'mpls.ldp':
        if (typeof value === 'boolean') doc.mplsLdp = value
        else doc.extras[key] = value
        break
      case 'mpls': {
        const split = splitModuleKey(value, 'ldp', boolShape)
        if (split === null) doc.extras[key] = value
        else {
          if (split.typed !== undefined) doc.mplsLdp = split.typed
          if (split.rest !== undefined) doc.extras[key] = split.rest
        }
        break
      }
      case 'vrfs': {
        const vrfs = vrfListShape(value)
        if (vrfs !== null) doc.vrfs = vrfs
        else doc.extras[key] = value
        break
      }
      case 'groups':
        doc.groups = parseGroups(value, doc)
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

  const memberships: { node: string; group: string }[] = []
  const rawNodes = raw['nodes']
  if (rawNodes === undefined) {
    // A bare document (fresh lab) is representable; emit blocks an empty save.
  } else if (Array.isArray(rawNodes)) {
    // Both list spellings netlab's create_node_dict accepts: a plain name, or
    // a mapping whose `name` key IS the node name (the rest are attributes).
    // Emit normalizes either to the mapping form — netlab's own model.
    for (const entry of rawNodes) {
      if (typeof entry === 'string') {
        doc.nodes.push(parseNode(entry, null, reasons, knownDevices, memberships))
      } else if (isRecord(entry)) {
        const { name, ...attrs } = entry
        if (typeof name === 'string') {
          doc.nodes.push(parseNode(name, attrs, reasons, knownDevices, memberships))
        } else reasons.push(`node list entry ${describe(entry)} is missing a "name"`)
      } else {
        reasons.push(`node list entry ${describe(entry)} is not a name or a mapping`)
      }
    }
  } else if (isRecord(rawNodes)) {
    for (const [name, attrs] of Object.entries(rawNodes)) {
      doc.nodes.push(parseNode(name, attrs, reasons, knownDevices, memberships))
    }
  } else {
    reasons.push('"nodes" must be a mapping or a list of names')
  }

  // netlab's add_node_level_groups: a node's own `group:` is appended to that
  // group's members, so the two spellings are the same fact. The builder
  // models membership ON the group, so fold them in and re-emit there —
  // a rewrite, hence a notice.
  for (const { node, group } of memberships) {
    let target = doc.groups.find((candidate) => candidate.name === group)
    if (target === undefined) {
      // netlab creates the group on demand; so must the builder, or the
      // membership would name a group that does not exist.
      target = { name: group, members: [] }
      doc.groups.push(target)
    }
    if (!target.members.includes(node)) target.members.push(node)
  }
  if (memberships.length > 0) {
    const nodes = [...new Set(memberships.map((entry) => entry.node))]
    notices.push(
      `${nodes.length === 1 ? `node "${nodes[0]}" declares` : `${nodes.length} nodes declare`} their own group membership — the builder records it on the group, and saving spells it there`,
    )
  }

  doc.links = parseLinks(raw['links'], declaredNodes(doc.nodes), reasons, notices)

  if (reasons.length > 0) return { ok: false, reasons }
  return { ok: true, doc, notices }
}

// --------------------------------------------------------------------------
// Emit
// --------------------------------------------------------------------------

/** The extras half of a split module key, when there is one to merge. A
 * non-mapping value under `bgp:`/`mpls:` was never split, so it stays an
 * ordinary extra. */
function moduleRest(extras: Extras | undefined, key: 'bgp' | 'mpls'): Extras | undefined {
  const value = extras?.[key]
  return isRecord(value) ? value : undefined
}

function nodeYaml(node: BuildNode): Record<string, unknown> | null {
  const out: Record<string, unknown> = {}
  if (node.device !== undefined) out['device'] = node.device
  if (node.image !== undefined) out[node.imageKey ?? 'image'] = node.image
  if (node.role !== undefined) out['role'] = node.role
  if (node.modules !== undefined) out['module'] = [...node.modules]
  const bgpRest = moduleRest(node.extras, 'bgp')
  const mplsRest = moduleRest(node.extras, 'mpls')
  moduleKeyYaml(out, 'bgp', 'as', node.bgpAs, bgpRest)
  moduleKeyYaml(out, 'mpls', 'vpn', node.mplsVpn, mplsRest)
  if (node.vrfs !== undefined && Object.keys(node.vrfs).length > 0) {
    out['vrfs'] = Object.fromEntries(
      Object.entries(node.vrfs).map(([name, attrs]) => [name, nodeVrfYaml(attrs)]),
    )
  }
  if (node.loopback !== undefined) out['loopback'] = loopbackYaml(node.loopback)
  if (node.config !== undefined) out['config'] = [...node.config]
  for (const [key, value] of Object.entries(node.extras ?? {})) {
    if ((key === 'bgp' && bgpRest !== undefined) || (key === 'mpls' && mplsRest !== undefined)) {
      continue // already merged with its typed subkey
    }
    out[key] = value
  }
  return Object.keys(out).length > 0 ? out : null
}

function groupYaml(group: BuildGroup): Record<string, unknown> | null {
  const out: Record<string, unknown> = {}
  if (group.members.length > 0) out['members'] = [...group.members]
  if (group.config !== undefined) out['config'] = [...group.config]
  for (const [key, value] of Object.entries(group.extras ?? {})) out[key] = value
  return Object.keys(out).length > 0 ? out : null
}

function bareEndpoint(endpoint: LinkEndpoint): boolean {
  return Object.keys(endpointAttrsYaml(endpoint)).length === 0
}

/** Canonical link emission: the terse string/list forms when the link carries
 * nothing but endpoints, the dict form (name first, endpoints in order,
 * attributes after) otherwise. Stubs always emit dict form — the one-key
 * mapping is the spelling netlab documents for them. */
function linkYaml(link: BuildLink): unknown {
  const endpoints = linkEndpoints(link)
  const bare =
    link.name === undefined &&
    link.prefix === undefined &&
    link.bandwidth === undefined &&
    link.mtu === undefined &&
    (link.extras === undefined || Object.keys(link.extras).length === 0) &&
    endpoints.every(bareEndpoint)
  // netlab splits the terse "a-b" form on '-', so a hyphenated endpoint name
  // (or a self-link, where "r1-r1" reads as two different nodes) can only be
  // spelled in the list form.
  const selfLink = new Set(endpoints.map((endpoint) => endpoint.node)).size !== endpoints.length
  const terse = bare && !selfLink && !endpoints.some((endpoint) => endpoint.node.includes('-'))
  if (terse && link.kind === 'p2p') return `${link.a.node}-${link.b.node}`
  if (bare && link.kind !== 'stub') return endpoints.map((endpoint) => endpoint.node)
  const out: Record<string, unknown> = {}
  if (link.name !== undefined) out['name'] = link.name
  if (selfLink) {
    // A node appears twice, which a mapping of node keys cannot spell — the
    // interfaces form is the equivalent netlab expands identically.
    out['interfaces'] = endpoints.map((endpoint) => ({
      node: endpoint.node,
      ...endpointAttrsYaml(endpoint),
    }))
  } else {
    for (const endpoint of endpoints) {
      out[endpoint.node] = bareEndpoint(endpoint) ? null : endpointAttrsYaml(endpoint)
    }
  }
  if (link.prefix !== undefined) out['prefix'] = link.prefix
  if (link.bandwidth !== undefined) out['bandwidth'] = link.bandwidth
  if (link.mtu !== undefined) out['mtu'] = link.mtu
  for (const [key, value] of Object.entries(link.extras ?? {})) out[key] = value
  return out
}

/** A flat list, or the dict-of-lists form when the links carry the named-list
 * grouping they were authored with (groups in first-appearance order). */
function linksYaml(links: readonly BuildLink[]): unknown {
  if (links[0]?.listName === undefined) return links.map(linkYaml)
  const grouped = new Map<string, unknown[]>()
  for (const link of links) {
    const listName = link.listName as string
    const bucket = grouped.get(listName)
    if (bucket === undefined) grouped.set(listName, [linkYaml(link)])
    else bucket.push(linkYaml(link))
  }
  return Object.fromEntries(grouped)
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
  const endpointNames = declaredNodes(doc.nodes)
  const vrfNames = new Set(declaredVrfs(doc))
  for (const node of doc.nodes) {
    // A node that pulls in a component takes its device from the component's
    // own nodes, so it needs none of its own.
    const fromComponent = node.extras?.['include'] !== undefined
    if (node.device === undefined && doc.defaultDevice === undefined && !fromComponent) {
      problems.push(`node "${node.name}" has no device and the lab has no default device`)
    }
    for (const vrf of Object.keys(node.vrfs ?? {})) {
      if (!vrfNames.has(vrf)) {
        problems.push(`node "${node.name}": vrf "${vrf}" is not declared under the top-level vrfs`)
      }
    }
  }
  doc.links.forEach((link, index) => {
    if (link.kind === 'lan' && link.members.length < 3) {
      problems.push(
        link.members.length < 2
          ? `LAN segment "${link.id}" needs at least three members — connect them or delete it`
          : `LAN segment "${link.id}" has two members, which is a point-to-point link — connect a third member or use a direct link`,
      )
    }
    // Same guard as the other extras levels, plus the link-specific rule: an
    // extras key naming any declared node would re-parse as an endpoint.
    const written = new Set(linkEndpoints(link).map((endpoint) => endpoint.node))
    if (link.name !== undefined) written.add('name')
    if (link.prefix !== undefined) written.add('prefix')
    if (link.bandwidth !== undefined) written.add('bandwidth')
    if (link.mtu !== undefined) written.add('mtu')
    for (const [key, value] of Object.entries(link.extras ?? {})) {
      const err = linkExtrasKeyError(key, value, endpointNames)
      if (err !== null) {
        problems.push(`link ${index + 1}: advanced property "${key}" — ${err}`)
      } else if (written.has(key)) {
        problems.push(
          `link ${index + 1}: advanced property "${key}" duplicates a builder-managed key — remove one of them`,
        )
      }
    }
  })
  // netlab's `links:` is EITHER a list or a mapping of named lists, so the
  // grouping is all-or-nothing. Parse and the canvas both keep it that way;
  // this catches an edge path rather than emitting an impossible document.
  const named = doc.links.filter((link) => link.listName !== undefined)
  if (named.length > 0 && named.length < doc.links.length) {
    const stray = doc.links.findIndex((link) => link.listName === undefined)
    problems.push(
      `link ${stray + 1} is not in a named list, but others are — links are either one list or all in named lists`,
    )
  }
  // netlab groups nest: a member may be another group, which broadcasts the
  // parent's data to ITS members.
  const groupNames = new Set(doc.groups.map((group) => group.name))
  for (const group of doc.groups) {
    // `_auto_create: true` asks netlab to create the members itself, so the
    // declared-node rule doesn't apply to that group.
    if (group.extras?.['_auto_create'] === true) continue
    for (const member of group.members) {
      if (!nodeNames.has(member) && !groupNames.has(member)) {
        problems.push(`group "${group.name}": member "${member}" is not a declared node or group`)
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
  if (doc.groups.length > 0 || doc.groupsExtras !== undefined) written.add('groups')
  if (doc.addressing !== undefined) written.add('addressing')
  extrasCollisions(doc.extras, written, 'lab', problems)
  for (const node of doc.nodes) {
    const nodeWritten = new Set<string>()
    if (node.device !== undefined) nodeWritten.add('device')
    if (node.image !== undefined) nodeWritten.add(node.imageKey ?? 'image')
    if (node.role !== undefined) nodeWritten.add('role')
    if (node.modules !== undefined) nodeWritten.add('module')
    if (node.bgpAs !== undefined) nodeWritten.add('bgp.as')
    if (node.mplsVpn !== undefined) nodeWritten.add('mpls.vpn')
    if (node.vrfs !== undefined && Object.keys(node.vrfs).length > 0) nodeWritten.add('vrfs')
    if (node.loopback !== undefined) nodeWritten.add('loopback')
    if (node.config !== undefined) nodeWritten.add('config')
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
  const bgpRest = moduleRest(doc.extras, 'bgp')
  const mplsRest = moduleRest(doc.extras, 'mpls')
  moduleKeyYaml(out, 'bgp', 'as', doc.bgpAs, bgpRest)
  moduleKeyYaml(out, 'mpls', 'ldp', doc.mplsLdp, mplsRest)
  if (doc.vrfs.length > 0) {
    out['vrfs'] = Object.fromEntries(doc.vrfs.map((vrf) => [vrf.name, vrfYaml(vrf)]))
  }
  if (doc.groups.length > 0 || doc.groupsExtras !== undefined) {
    out['groups'] = {
      ...doc.groupsExtras,
      ...Object.fromEntries(doc.groups.map((group) => [group.name, groupYaml(group)])),
    }
  }
  if (doc.addressing !== undefined) {
    out['addressing'] = { mgmt: { ...doc.addressing.mgmt } }
  }
  for (const [key, value] of Object.entries(doc.extras)) {
    if ((key === 'bgp' && bgpRest !== undefined) || (key === 'mpls' && mplsRest !== undefined)) {
      continue // already merged with its typed subkey
    }
    out[key] = value
  }
  out['nodes'] = Object.fromEntries(doc.nodes.map((node) => [node.name, nodeYaml(node)]))
  out['links'] = linksYaml(doc.links)
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

export function nextStubId(doc: BuildDoc): string {
  let max = 0
  for (const link of doc.links) {
    if (link.kind === 'stub') {
      const n = Number(link.id.slice('stub:'.length))
      if (Number.isInteger(n) && n > max) max = n
    }
  }
  return `stub:${max + 1}`
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
    vrfs: [...doc.vrfs]
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((vrf) => ({ name: vrf.name, extras: canonicalExtras(vrf.extras) })),
    groups: doc.groups.map((group) => ({
      name: group.name,
      members: group.members,
      config: group.config ?? null,
      extras: canonicalExtras(group.extras),
    })),
    groupsExtras: canonicalExtras(doc.groupsExtras),
    addressing: doc.addressing ?? null,
    extras: canonicalExtras(doc.extras),
    nodes: doc.nodes.map((node) => ({
      name: node.name,
      device: node.device ?? null,
      image: node.image ?? null,
      imageKey: node.imageKey ?? null,
      role: node.role ?? null,
      modules: node.modules ?? null,
      bgpAs: node.bgpAs ?? null,
      mplsVpn: node.mplsVpn ?? null,
      loopback:
        node.loopback === undefined
          ? null
          : {
              ipv4: node.loopback.ipv4 ?? null,
              ipv6: node.loopback.ipv6 ?? null,
              extras: canonicalExtras(node.loopback.extras),
            },
      config: node.config ?? null,
      vrfs:
        node.vrfs !== undefined && Object.keys(node.vrfs).length > 0
          ? Object.entries(node.vrfs)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([name, attrs]) => ({
                name,
                loopback: attrs.loopback ?? null,
                extras: canonicalExtras(attrs.extras),
              }))
          : null,
      extras: canonicalExtras(node.extras),
    })),
    links: doc.links.map((link) => ({
      kind: link.kind,
      name: link.name ?? null,
      prefix: link.prefix ?? null,
      bandwidth: link.bandwidth ?? null,
      mtu: link.mtu ?? null,
      listName: link.listName ?? null,
      extras: canonicalExtras(link.extras),
      endpoints: linkEndpoints(link).map((endpoint) => ({
        node: endpoint.node,
        ifname: endpoint.ifname ?? null,
        ipv4: endpoint.ipv4 ?? null,
        ipv6: endpoint.ipv6 ?? null,
        extras: canonicalExtras(endpoint.extras),
      })),
    })),
  }
}

/** Round-trip equality, ignoring LAN/stub ids (session metadata reassigned on
 * every parse), empty-vs-absent vrf membership records, and extras key
 * order. */
export function buildDocEquals(a: BuildDoc, b: BuildDoc): boolean {
  return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b))
}
