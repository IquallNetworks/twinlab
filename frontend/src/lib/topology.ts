import { parse } from 'yaml'

// Best-effort client-side reading of a netlab definition, for the topology
// canvas. netlab's syntax is far richer than any canvas (link groups, VLANs,
// dotted attributes, …): everything this module cannot resolve is COUNTED in
// `unrendered` and surfaced by the UI — never silently dropped. Pure module
// (no React) on purpose: it is also the foundation of the Phase-4 builder's
// round-trip. The generated containerlab topology (and eventually a backend
// link table) stays the ground truth; this is a faithful sketch.

export interface TopoNode {
  name: string
  device?: string
  // True when the node is only referenced by a link, not declared under
  // `nodes:` — rendered, but the definition should really declare it.
  implicit?: boolean
}

export type TopoLink =
  | { kind: 'p2p'; a: string; b: string }
  // 3+ endpoints: drawn as a LAN hub pseudo-node with a spoke per member.
  | { kind: 'lan'; id: string; members: string[] }

export interface ParsedTopology {
  nodes: TopoNode[]
  links: TopoLink[]
  unrendered: number
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nodeDevice(attrs: unknown): string | undefined {
  if (!isRecord(attrs)) return undefined
  const device = attrs['device']
  return typeof device === 'string' ? device : undefined
}

/** The topology-wide default device: netlab accepts both the nested
 * `defaults: {device}` form and the dotted literal `defaults.device` key
 * (which the yaml parser keeps as ONE string key). */
function defaultDevice(doc: Record<string, unknown>): string | undefined {
  const dotted = doc['defaults.device']
  if (typeof dotted === 'string') return dotted
  const defaults = doc['defaults']
  if (isRecord(defaults)) {
    const device = defaults['device']
    if (typeof device === 'string') return device
  }
  return undefined
}

interface LinkAccumulator {
  links: TopoLink[]
  unrendered: number
  lanCount: number
  // Nodes referenced by links but not declared — promoted to implicit nodes.
  referenced: Set<string>
}

/** Endpoints of one link entry, or null when the entry can't be resolved. */
function linkEndpoints(entry: unknown, declared: ReadonlySet<string>): string[] | null {
  if (typeof entry === 'string') {
    // "a-b" (netlab node names cannot contain hyphens, so splitting is safe).
    const parts = entry.split('-').filter((p) => p !== '')
    return parts.length >= 2 ? parts : null
  }
  if (Array.isArray(entry)) {
    const members = entry.filter((m): m is string => typeof m === 'string')
    return members.length >= 2 && members.length === entry.length ? members : null
  }
  if (isRecord(entry)) {
    // Explicit interfaces list wins: `interfaces: [{node: r1}, {node: r2}]`.
    const interfaces = entry['interfaces']
    if (Array.isArray(interfaces)) {
      const members = interfaces
        .map((i) => (isRecord(i) && typeof i['node'] === 'string' ? i['node'] : null))
        .filter((n): n is string => n !== null)
      return members.length >= 2 ? members : null
    }
    // Dict form: keys that name declared nodes are endpoints; the rest are
    // link attributes (bandwidth, prefix, vlan…).
    const members = Object.keys(entry).filter((key) => declared.has(key))
    return members.length >= 2 ? members : null
  }
  return null
}

function collectLink(entry: unknown, declared: ReadonlySet<string>, acc: LinkAccumulator): void {
  // Link group: shared attributes over a `members` list — recurse.
  if (isRecord(entry) && Array.isArray(entry['members'])) {
    for (const member of entry['members']) collectLink(member, declared, acc)
    return
  }
  const endpoints = linkEndpoints(entry, declared)
  if (endpoints === null) {
    acc.unrendered += 1
    return
  }
  for (const name of endpoints) acc.referenced.add(name)
  if (endpoints.length === 2) {
    // Non-null asserts are safe by the length check, but destructure instead.
    const [a, b] = endpoints as [string, string]
    acc.links.push({ kind: 'p2p', a, b })
  } else {
    acc.lanCount += 1
    acc.links.push({ kind: 'lan', id: `lan:${acc.lanCount}`, members: endpoints })
  }
}

/** Parse a stored netlab definition into a render model. Returns null when
 * the document is not valid YAML or not a mapping at all. */
export function parseTopology(definition: string): ParsedTopology | null {
  let doc: unknown
  try {
    doc = parse(definition)
  } catch {
    return null
  }
  if (!isRecord(doc)) return null

  const fallbackDevice = defaultDevice(doc)
  const nodes: TopoNode[] = []
  const declared = new Set<string>()

  const rawNodes = doc['nodes']
  if (Array.isArray(rawNodes)) {
    for (const entry of rawNodes) {
      if (typeof entry === 'string') {
        declared.add(entry)
        nodes.push({ name: entry, device: fallbackDevice })
      }
    }
  } else if (isRecord(rawNodes)) {
    for (const [name, attrs] of Object.entries(rawNodes)) {
      declared.add(name)
      nodes.push({ name, device: nodeDevice(attrs) ?? fallbackDevice })
    }
  }

  const acc: LinkAccumulator = { links: [], unrendered: 0, lanCount: 0, referenced: new Set() }
  const rawLinks = doc['links']
  if (Array.isArray(rawLinks)) {
    for (const entry of rawLinks) collectLink(entry, declared, acc)
  } else if (isRecord(rawLinks)) {
    // Structured form: a dict whose values are link lists.
    for (const value of Object.values(rawLinks)) {
      if (Array.isArray(value)) {
        for (const entry of value) collectLink(entry, declared, acc)
      } else {
        acc.unrendered += 1
      }
    }
  }

  for (const name of acc.referenced) {
    if (!declared.has(name)) {
      declared.add(name)
      nodes.push({ name, device: fallbackDevice, implicit: true })
    }
  }

  return { nodes, links: acc.links, unrendered: acc.unrendered }
}
