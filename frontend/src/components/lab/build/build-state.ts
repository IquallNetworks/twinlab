import type { BuildDoc, BuildGroup, BuildLink, BuildNode, Extras, LinkEndpoint } from '@/lib/build-doc'

// The builder's editing state: the BuildDoc is the single source of truth
// (canvas nodes/edges and the inspector are pure derivations of it), plus a
// dirty flag (any mutation sets it, reset clears it) and the current
// selection. Pure reducer — every action returns a new state and keeps the
// selection coherent (deleting the selected thing falls back to the lab).

export type Selection =
  | { kind: 'lab' } // nothing selected → the lab-settings inspector
  | { kind: 'node'; name: string }
  | { kind: 'lan'; linkIndex: number }
  | { kind: 'link'; linkIndex: number }
  | { kind: 'stub'; linkIndex: number }
  | { kind: 'member'; linkIndex: number; node: string }

export interface BuilderState {
  doc: BuildDoc
  dirty: boolean
  selection: Selection
}

export type BuilderAction =
  | { type: 'reset'; doc: BuildDoc } // load / discard / post-save re-parse
  | { type: 'add-node'; name: string; device: string }
  | { type: 'add-lan'; id: string }
  | { type: 'connect'; source: string; target: string } // canvas ids: node name or `lan:<n>`
  | { type: 'add-stub'; id: string; node: string }
  | { type: 'delete-node'; name: string }
  | { type: 'delete-link'; linkIndex: number }
  | { type: 'remove-member'; linkIndex: number; node: string }
  | { type: 'patch-link'; linkIndex: number; patch: { name?: string; extras?: Extras } }
  // Replace one endpoint's attributes (undefined clears them).
  | { type: 'patch-endpoint'; linkIndex: number; node: string; extras: Extras | undefined }
  | { type: 'rename-node'; from: string; to: string }
  | { type: 'patch-node'; name: string; patch: Partial<Omit<BuildNode, 'name'>> }
  | {
      type: 'patch-lab'
      patch: Partial<Pick<BuildDoc, 'defaultDevice' | 'modules' | 'bgpAs' | 'mplsLdp' | 'extras'>>
    }
  | { type: 'add-vrf'; name: string }
  | { type: 'remove-vrf'; name: string }
  | { type: 'add-group'; name: string }
  | { type: 'delete-group'; name: string }
  | { type: 'rename-group'; from: string; to: string }
  | { type: 'patch-group'; name: string; patch: Partial<Omit<BuildGroup, 'name'>> }
  | { type: 'select'; selection: Selection }

export function initialBuilderState(doc: BuildDoc): BuilderState {
  return { doc, dirty: false, selection: { kind: 'lab' } }
}

const isLanId = (id: string): boolean => id.startsWith('lan:')
const isStubId = (id: string): boolean => id.startsWith('stub:')

export type ConnectVerdict = { ok: true } | { ok: false; reason: string }

/** Shared between React Flow's isValidConnection (live feedback) and the
 * connect action itself. Canvas ids: a device node's id is its name, a LAN
 * hub's id is the link's `lan:<n>`. */
export function validateConnect(doc: BuildDoc, source: string, target: string): ConnectVerdict {
  if (source === target) return { ok: false, reason: 'a node cannot link to itself' }
  if (isStubId(source) || isStubId(target)) {
    return { ok: false, reason: 'a stub link has only its one endpoint' }
  }
  if (isLanId(source) && isLanId(target)) {
    return { ok: false, reason: 'LAN segments cannot be linked to each other' }
  }
  const lanId = isLanId(source) ? source : isLanId(target) ? target : null
  const device = isLanId(source) ? target : source
  if (!doc.nodes.some((node) => node.name === device)) {
    return { ok: false, reason: `unknown node "${device}"` }
  }
  if (lanId !== null) {
    const lan = doc.links.find((link) => link.kind === 'lan' && link.id === lanId)
    if (lan === undefined || lan.kind !== 'lan') {
      return { ok: false, reason: `unknown LAN segment "${lanId}"` }
    }
    if (lan.members.some((member) => member.node === device)) {
      return { ok: false, reason: `${device} is already a member of this segment` }
    }
  }
  // device ↔ device: parallel links are legitimate netlab — always allowed.
  return { ok: true }
}

/** Apply a patch where an explicitly-undefined value DELETES the field
 * (unset device, clear a module override) and absent keys are untouched. */
function applyPatch<T extends object>(target: T, patch: Partial<T>): T {
  const out = { ...target }
  for (const key of Object.keys(patch) as (keyof T)[]) {
    const value = patch[key]
    if (value === undefined) delete out[key]
    else out[key] = value
  }
  return out
}

function connect(doc: BuildDoc, source: string, target: string): BuildDoc {
  const lanId = isLanId(source) ? source : isLanId(target) ? target : null
  const device = isLanId(source) ? target : source
  if (lanId === null) {
    const link: BuildLink = { kind: 'p2p', a: { node: source }, b: { node: target } }
    return { ...doc, links: [...doc.links, link] }
  }
  return {
    ...doc,
    links: doc.links.map((link) =>
      link.kind === 'lan' && link.id === lanId
        ? { ...link, members: [...link.members, { node: device }] }
        : link,
    ),
  }
}

function deleteNode(doc: BuildDoc, name: string): BuildDoc {
  const links: BuildLink[] = []
  for (const link of doc.links) {
    if (link.kind === 'p2p') {
      if (link.a.node !== name && link.b.node !== name) links.push(link)
    } else if (link.kind === 'stub') {
      if (link.endpoint.node !== name) links.push(link)
    } else {
      const members = link.members.filter((member) => member.node !== name)
      // A segment everyone has left is gone; partially-emptied ones stay
      // (the emitter blocks a <3-member LAN loudly at save).
      if (members.length > 0) links.push({ ...link, members })
    }
  }
  return {
    ...doc,
    nodes: doc.nodes.filter((node) => node.name !== name),
    links,
    // Group memberships follow the node out — an emptied group stays (it may
    // still carry config/extras worth keeping).
    groups: doc.groups.map((group) =>
      group.members.includes(name)
        ? { ...group, members: group.members.filter((member) => member !== name) }
        : group,
    ),
  }
}

function renameInLinks(links: readonly BuildLink[], from: string, to: string): BuildLink[] {
  const rename = (endpoint: LinkEndpoint): LinkEndpoint =>
    endpoint.node === from ? { ...endpoint, node: to } : endpoint
  return links.map((link) => {
    switch (link.kind) {
      case 'p2p':
        return { ...link, a: rename(link.a), b: rename(link.b) }
      case 'stub':
        return { ...link, endpoint: rename(link.endpoint) }
      case 'lan':
        return { ...link, members: link.members.map(rename) }
    }
  })
}

/** Replace one endpoint's attributes on any link kind. */
function patchEndpoint(link: BuildLink, node: string, extras: Extras | undefined): BuildLink {
  const apply = (endpoint: LinkEndpoint): LinkEndpoint =>
    endpoint.node !== node
      ? endpoint
      : extras === undefined || Object.keys(extras).length === 0
        ? { node: endpoint.node }
        : { node: endpoint.node, extras }
  switch (link.kind) {
    case 'p2p':
      return { ...link, a: apply(link.a), b: apply(link.b) }
    case 'stub':
      return { ...link, endpoint: apply(link.endpoint) }
    case 'lan':
      return { ...link, members: link.members.map(apply) }
  }
}

/** Does the selection still point at something that exists? Link indices are
 * positional, so any link-array reshaping funnels through this. */
function coherentSelection(selection: Selection, doc: BuildDoc): Selection {
  switch (selection.kind) {
    case 'lab':
      return selection
    case 'node':
      return doc.nodes.some((node) => node.name === selection.name)
        ? selection
        : { kind: 'lab' }
    case 'link': {
      const link = doc.links[selection.linkIndex]
      return link !== undefined && link.kind === 'p2p' ? selection : { kind: 'lab' }
    }
    case 'lan': {
      const link = doc.links[selection.linkIndex]
      return link !== undefined && link.kind === 'lan' ? selection : { kind: 'lab' }
    }
    case 'stub': {
      const link = doc.links[selection.linkIndex]
      return link !== undefined && link.kind === 'stub' ? selection : { kind: 'lab' }
    }
    case 'member': {
      const link = doc.links[selection.linkIndex]
      return link !== undefined &&
        link.kind === 'lan' &&
        link.members.some((member) => member.node === selection.node)
        ? selection
        : { kind: 'lab' }
    }
  }
}

export function builderReducer(state: BuilderState, action: BuilderAction): BuilderState {
  switch (action.type) {
    case 'reset':
      return initialBuilderState(action.doc)
    case 'select':
      return { ...state, selection: action.selection }
    case 'add-node': {
      if (state.doc.nodes.some((node) => node.name === action.name)) return state
      const doc = {
        ...state.doc,
        nodes: [...state.doc.nodes, { name: action.name, device: action.device }],
      }
      return { doc, dirty: true, selection: { kind: 'node', name: action.name } }
    }
    case 'add-lan': {
      const link: BuildLink = { kind: 'lan', id: action.id, members: [] }
      const doc = { ...state.doc, links: [...state.doc.links, link] }
      return { doc, dirty: true, selection: { kind: 'lan', linkIndex: doc.links.length - 1 } }
    }
    case 'add-stub': {
      if (!state.doc.nodes.some((node) => node.name === action.node)) return state
      const link: BuildLink = { kind: 'stub', id: action.id, endpoint: { node: action.node } }
      const doc = { ...state.doc, links: [...state.doc.links, link] }
      return { doc, dirty: true, selection: { kind: 'stub', linkIndex: doc.links.length - 1 } }
    }
    case 'connect': {
      if (!validateConnect(state.doc, action.source, action.target).ok) return state
      return {
        doc: connect(state.doc, action.source, action.target),
        dirty: true,
        selection: state.selection,
      }
    }
    case 'delete-node': {
      const doc = deleteNode(state.doc, action.name)
      return { doc, dirty: true, selection: coherentSelection(state.selection, doc) }
    }
    case 'delete-link': {
      const doc = {
        ...state.doc,
        links: state.doc.links.filter((_, index) => index !== action.linkIndex),
      }
      return { doc, dirty: true, selection: coherentSelection(state.selection, doc) }
    }
    case 'remove-member': {
      const doc = {
        ...state.doc,
        links: state.doc.links.map((link, index) =>
          index === action.linkIndex && link.kind === 'lan'
            ? { ...link, members: link.members.filter((member) => member.node !== action.node) }
            : link,
        ),
      }
      return { doc, dirty: true, selection: coherentSelection(state.selection, doc) }
    }
    case 'patch-link': {
      const doc = {
        ...state.doc,
        links: state.doc.links.map((link, index) => {
          if (index !== action.linkIndex) return link
          const next = { ...link }
          if ('name' in action.patch) {
            if (action.patch.name === undefined || action.patch.name === '') delete next.name
            else next.name = action.patch.name
          }
          if ('extras' in action.patch) {
            const extras = action.patch.extras
            if (extras === undefined || Object.keys(extras).length === 0) delete next.extras
            else next.extras = extras
          }
          return next
        }),
      }
      return { ...state, doc, dirty: true }
    }
    case 'patch-endpoint': {
      const doc = {
        ...state.doc,
        links: state.doc.links.map((link, index) =>
          index === action.linkIndex ? patchEndpoint(link, action.node, action.extras) : link,
        ),
      }
      return { ...state, doc, dirty: true }
    }
    case 'rename-node': {
      if (action.from === action.to) return state
      if (state.doc.nodes.some((node) => node.name === action.to)) return state
      const doc = {
        ...state.doc,
        nodes: state.doc.nodes.map((node) =>
          node.name === action.from ? { ...node, name: action.to } : node,
        ),
        links: renameInLinks(state.doc.links, action.from, action.to),
        groups: state.doc.groups.map((group) =>
          group.members.includes(action.from)
            ? {
                ...group,
                members: group.members.map((member) =>
                  member === action.from ? action.to : member,
                ),
              }
            : group,
        ),
      }
      const selection: Selection =
        state.selection.kind === 'node' && state.selection.name === action.from
          ? { kind: 'node', name: action.to }
          : coherentSelection(state.selection, doc)
      return { doc, dirty: true, selection }
    }
    case 'patch-node': {
      const doc = {
        ...state.doc,
        nodes: state.doc.nodes.map((node) =>
          node.name === action.name ? { ...applyPatch(node, action.patch), name: node.name } : node,
        ),
      }
      return { ...state, doc, dirty: true }
    }
    case 'patch-lab':
      return { ...state, doc: applyPatch<BuildDoc>(state.doc, action.patch), dirty: true }
    case 'add-vrf': {
      if (state.doc.vrfs.includes(action.name)) return state
      return {
        ...state,
        doc: { ...state.doc, vrfs: [...state.doc.vrfs, action.name] },
        dirty: true,
      }
    }
    case 'remove-vrf': {
      const doc = {
        ...state.doc,
        vrfs: state.doc.vrfs.filter((name) => name !== action.name),
        nodes: state.doc.nodes.map((node) => {
          if (node.vrfs === undefined || !(action.name in node.vrfs)) return node
          const vrfs = { ...node.vrfs }
          delete vrfs[action.name]
          return Object.keys(vrfs).length > 0
            ? { ...node, vrfs }
            : { ...applyPatch(node, { vrfs: undefined }) }
        }),
      }
      return { ...state, doc, dirty: true }
    }
    case 'add-group': {
      if (state.doc.groups.some((group) => group.name === action.name)) return state
      const doc = {
        ...state.doc,
        groups: [...state.doc.groups, { name: action.name, members: [] }],
      }
      return { ...state, doc, dirty: true }
    }
    case 'delete-group': {
      const doc = {
        ...state.doc,
        groups: state.doc.groups.filter((group) => group.name !== action.name),
      }
      return { ...state, doc, dirty: true }
    }
    case 'rename-group': {
      if (action.from === action.to) return state
      if (state.doc.groups.some((group) => group.name === action.to)) return state
      const doc = {
        ...state.doc,
        groups: state.doc.groups.map((group) =>
          group.name === action.from ? { ...group, name: action.to } : group,
        ),
      }
      return { ...state, doc, dirty: true }
    }
    case 'patch-group': {
      const doc = {
        ...state.doc,
        groups: state.doc.groups.map((group) =>
          group.name === action.name
            ? { ...applyPatch(group, action.patch), name: group.name }
            : group,
        ),
      }
      return { ...state, doc, dirty: true }
    }
  }
}
