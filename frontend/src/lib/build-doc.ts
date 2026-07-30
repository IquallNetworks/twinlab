import { parse, stringify } from 'yaml'

import { BUILDER_MODULES, catalogDevice, type BuilderModule } from './device-catalog'

// The builder's document model: a STRICT, typed subset of netlab syntax the
// visual builder can faithfully edit and re-emit. parseBuildDoc is a gate,
// not a best-effort reader (that is lib/topology.ts): any content outside the
// subset yields human-readable reasons and the Build tab falls back to text
// editing — definition content is never silently dropped.
//
// The subset: nodes + p2p/LAN links, the proven module set (ospf/bgp/mpls/vrf)
// with bgp.as, mpls.ldp, mpls.vpn and vrf membership, the curated device
// catalog, and the keys the backend itself injects on save (name,
// addressing.mgmt). Emission is canonical; the round-trip invariant is:
// for any doc emitBuildDoc accepts, parseBuildDoc(emit(doc)) equals doc
// (up to LAN ids, which are session metadata).
//
// Pure module (no React, no `@/` alias imports) so a plain node script can
// exercise the round-trip.

export { BUILDER_MODULES, type BuilderModule } from './device-catalog'

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
  // Injected by the backend on save (the lab's allocated mgmt subnet);
  // preserved verbatim.
  addressing?: MgmtAddressing
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

function parseModuleList(value: unknown, where: string, reasons: string[]): BuilderModule[] {
  if (!Array.isArray(value)) {
    reasons.push(`${where} must be a list of modules`)
    return []
  }
  const modules: BuilderModule[] = []
  for (const entry of value) {
    if (typeof entry === 'string' && (BUILDER_MODULES as readonly string[]).includes(entry)) {
      modules.push(entry as BuilderModule)
    } else {
      reasons.push(
        `${where} includes ${describe(entry)}, outside the builder's module set (${BUILDER_MODULES.join(', ')})`,
      )
    }
  }
  return modules
}

function parseDevice(value: unknown, where: string, reasons: string[]): string | undefined {
  if (typeof value !== 'string') {
    reasons.push(`${where} must be a device name, got ${describe(value)}`)
    return undefined
  }
  if (catalogDevice(value) === undefined) {
    reasons.push(`${where} device "${value}" is not in the builder's catalog`)
    return undefined
  }
  return value
}

function parseAddressing(value: unknown, reasons: string[]): MgmtAddressing | undefined {
  const bad = (): undefined => {
    reasons.push(
      '"addressing" carries more than the backend-injected management subnet (addressing.mgmt.ipv4)',
    )
    return undefined
  }
  if (!isRecord(value)) return bad()
  const keys = Object.keys(value)
  const mgmt = value['mgmt']
  if (keys.length !== 1 || !isRecord(mgmt)) return bad()
  const ipv4 = mgmt['ipv4']
  const network = mgmt['_network']
  if (typeof ipv4 !== 'string') return bad()
  for (const key of Object.keys(mgmt)) {
    if (key !== 'ipv4' && key !== '_network') return bad()
  }
  if (network !== undefined && typeof network !== 'string') return bad()
  return { mgmt: network === undefined ? { ipv4 } : { ipv4, _network: network } }
}

function parseNodeVrfs(
  value: unknown,
  nodeName: string,
  globalVrfs: readonly string[],
  reasons: string[],
): Record<string, BuildNodeVrf> | undefined {
  if (!isRecord(value)) {
    reasons.push(`node "${nodeName}": "vrfs" must be a mapping`)
    return undefined
  }
  const vrfs: Record<string, BuildNodeVrf> = {}
  for (const [vrfName, attrs] of Object.entries(value)) {
    if (!globalVrfs.includes(vrfName)) {
      reasons.push(`node "${nodeName}": vrf "${vrfName}" is not declared under the top-level vrfs`)
      continue
    }
    if (attrs === null) {
      vrfs[vrfName] = {}
      continue
    }
    if (!isRecord(attrs)) {
      reasons.push(`node "${nodeName}": vrf "${vrfName}" must be empty or a mapping`)
      continue
    }
    const entry: BuildNodeVrf = {}
    for (const [key, attr] of Object.entries(attrs)) {
      if (key === 'loopback' && typeof attr === 'boolean') {
        entry.loopback = attr
      } else {
        reasons.push(
          `node "${nodeName}": vrf "${vrfName}" attribute "${key}" is not supported by the builder`,
        )
      }
    }
    vrfs[vrfName] = entry
  }
  return vrfs
}

function parseNode(
  name: string,
  attrs: unknown,
  globalVrfs: readonly string[],
  reasons: string[],
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
  for (const [key, value] of Object.entries(attrs)) {
    switch (key) {
      case 'device':
        node.device = parseDevice(value, `node "${name}":`, reasons)
        break
      case 'image':
        if (typeof value === 'string') node.image = value
        else reasons.push(`node "${name}": "image" must be a string`)
        break
      case 'module':
        node.modules = parseModuleList(value, `node "${name}": module`, reasons)
        break
      case 'bgp.as':
        if (typeof value === 'number') node.bgpAs = value
        else reasons.push(`node "${name}": "bgp.as" must be a number`)
        break
      case 'bgp':
        if (isRecord(value) && Object.keys(value).length === 1 && typeof value['as'] === 'number') {
          node.bgpAs = value['as']
        } else {
          reasons.push(`node "${name}": "bgp" carries more than "as", or a non-numeric "as"`)
        }
        break
      case 'mpls.vpn':
        if (typeof value === 'boolean') node.mplsVpn = value
        else reasons.push(`node "${name}": "mpls.vpn" must be a boolean`)
        break
      case 'mpls':
        if (
          isRecord(value) &&
          Object.keys(value).length === 1 &&
          typeof value['vpn'] === 'boolean'
        ) {
          node.mplsVpn = value['vpn']
        } else {
          reasons.push(`node "${name}": "mpls" carries more than a boolean "vpn"`)
        }
        break
      case 'vrfs':
        node.vrfs = parseNodeVrfs(value, name, globalVrfs, reasons)
        break
      default:
        reasons.push(`node "${name}": attribute "${key}" is not supported by the builder`)
    }
  }
  return node
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

/** The strict gate: parse a stored definition into the builder's model,
 * collecting EVERY reason it can't be represented (never fail-fast — the
 * notice lists them all). */
export function parseBuildDoc(definition: string): BuildDocResult {
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
  const doc: BuildDoc = { modules: [], vrfs: [], nodes: [], links: [] }

  for (const [key, value] of Object.entries(raw)) {
    switch (key) {
      case 'name':
        if (typeof value === 'string') doc.name = value
        else reasons.push('top-level "name" must be a string')
        break
      case 'provider':
        if (typeof value === 'string') doc.provider = value
        else reasons.push('top-level "provider" must be a string')
        break
      case 'defaults.device':
        doc.defaultDevice = parseDevice(value, 'default', reasons)
        break
      case 'defaults':
        if (isRecord(value)) {
          for (const [defKey, defValue] of Object.entries(value)) {
            if (defKey === 'device') doc.defaultDevice = parseDevice(defValue, 'default', reasons)
            else reasons.push(`defaults key "${defKey}" is not supported by the builder`)
          }
        } else {
          reasons.push('"defaults" must be a mapping')
        }
        break
      case 'module':
        doc.modules = parseModuleList(value, 'module', reasons)
        break
      case 'bgp.as':
        if (typeof value === 'number') doc.bgpAs = value
        else reasons.push('"bgp.as" must be a number')
        break
      case 'bgp':
        if (isRecord(value) && Object.keys(value).length === 1 && typeof value['as'] === 'number') {
          doc.bgpAs = value['as']
        } else {
          reasons.push('"bgp" carries more than "as", or a non-numeric "as"')
        }
        break
      case 'mpls.ldp':
        if (typeof value === 'boolean') doc.mplsLdp = value
        else reasons.push('"mpls.ldp" must be a boolean')
        break
      case 'mpls':
        if (
          isRecord(value) &&
          Object.keys(value).length === 1 &&
          typeof value['ldp'] === 'boolean'
        ) {
          doc.mplsLdp = value['ldp']
        } else {
          reasons.push('"mpls" carries more than a boolean "ldp"')
        }
        break
      case 'vrfs':
        if (isRecord(value)) {
          for (const [vrfName, attrs] of Object.entries(value)) {
            if (!EXISTING_NAME_RE.test(vrfName) || vrfName.length > NODE_NAME_MAX) {
              reasons.push(`vrf name "${vrfName}" is outside the builder's rules`)
            } else if (attrs === null || (isRecord(attrs) && Object.keys(attrs).length === 0)) {
              doc.vrfs.push(vrfName)
            } else {
              reasons.push(
                `vrf "${vrfName}" carries attributes the builder can't represent (rd, rt, import/export, …)`,
              )
            }
          }
        } else {
          reasons.push('"vrfs" must be a mapping of vrf names')
        }
        break
      case 'addressing':
        doc.addressing = parseAddressing(value, reasons)
        break
      case 'nodes':
      case 'links':
        break // handled below, in order (links need the declared node names)
      default:
        reasons.push(`top-level key "${key}" is not supported by the builder`)
    }
  }

  const rawNodes = raw['nodes']
  if (rawNodes === undefined) {
    // A bare document (fresh lab) is representable; emit blocks an empty save.
  } else if (Array.isArray(rawNodes)) {
    for (const entry of rawNodes) {
      if (typeof entry === 'string') doc.nodes.push(parseNode(entry, null, doc.vrfs, reasons))
      else reasons.push(`node list entry ${describe(entry)} is not a plain name`)
    }
  } else if (isRecord(rawNodes)) {
    for (const [name, attrs] of Object.entries(rawNodes)) {
      doc.nodes.push(parseNode(name, attrs, doc.vrfs, reasons))
    }
  } else {
    reasons.push('"nodes" must be a mapping or a list of names')
  }

  const declared = new Set(doc.nodes.map((node) => node.name))
  doc.links = parseLinks(raw['links'], declared, reasons)

  if (reasons.length > 0) return { ok: false, reasons }
  return { ok: true, doc }
}

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
  return Object.keys(out).length > 0 ? out : null
}

/** Canonical emission. Problems are SAVE BLOCKERS shown to the user — the
 * emitter never silently fixes a doc (a 2-member "LAN" is a p2p link, a
 * device is intentful and never defaulted). */
export function emitBuildDoc(doc: BuildDoc): EmitResult {
  const problems: string[] = []
  if (doc.nodes.length === 0) problems.push('the lab has no nodes yet')
  for (const node of doc.nodes) {
    if (node.device === undefined && doc.defaultDevice === undefined) {
      problems.push(`node "${node.name}" has no device and the lab has no default device`)
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
  if (doc.addressing !== undefined) {
    out['addressing'] = { mgmt: { ...doc.addressing.mgmt } }
  }
  out['nodes'] = Object.fromEntries(doc.nodes.map((node) => [node.name, nodeYaml(node)]))
  out['links'] = doc.links.map((link) =>
    link.kind === 'p2p' ? `${link.a}-${link.b}` : [...link.members],
  )
  return { ok: true, yaml: stringify(out) }
}

export function emptyBuildDoc(): BuildDoc {
  // provider clab: the only provider this deployment deploys through.
  return { provider: 'clab', modules: [], vrfs: [], nodes: [], links: [] }
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

function canonical(doc: BuildDoc): unknown {
  return {
    name: doc.name ?? null,
    provider: doc.provider ?? null,
    defaultDevice: doc.defaultDevice ?? null,
    modules: doc.modules,
    bgpAs: doc.bgpAs ?? null,
    mplsLdp: doc.mplsLdp ?? null,
    vrfs: [...doc.vrfs].sort(),
    addressing: doc.addressing ?? null,
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
    })),
    links: doc.links.map((link) =>
      link.kind === 'p2p'
        ? { kind: 'p2p', a: link.a, b: link.b }
        : { kind: 'lan', members: link.members },
    ),
  }
}

/** Round-trip equality, ignoring LAN ids (session metadata reassigned on
 * every parse) and empty-vs-absent vrf membership records. */
export function buildDocEquals(a: BuildDoc, b: BuildDoc): boolean {
  return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b))
}
