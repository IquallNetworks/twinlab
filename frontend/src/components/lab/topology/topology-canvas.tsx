import { useQueries, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type EdgeMouseHandler,
  type NodeMouseHandler,
} from '@xyflow/react'
import { Download, LayoutGrid, Map as MapIcon, MoveHorizontal, MoveVertical } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTheme } from 'next-themes'
import { toast } from 'sonner'

import { LinkImpairment } from '@/components/lab/link-impairment'
import { NodeConnectDrawer } from '@/components/lab/node-connect-drawer'
import { NodeControls } from '@/components/lab/node-controls'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { linkOperBadgeVariant, nodeStateBadgeVariant } from '@/lib/format'
import {
  PERM_LAB_CONFIGURE,
  PERM_LAB_READ,
  PERM_LAB_TERMINAL,
} from '@/lib/lab-permissions'
import { labLayoutQueryOptions, labLinksQueryOptions, nodeNetemQueryOptions } from '@/lib/queries'
import type { LabDetail, LabLink, LinkOperState } from '@/lib/schemas'
import type { ParsedTopology } from '@/lib/topology'

import { DeviceNode } from './device-node'
import {
  DEVICE_H,
  DEVICE_W,
  LAN_H,
  LAN_W,
  NOT_DEPLOYED,
  type AppNode,
} from './flow-types'
import { LanNode } from './lan-node'
import { layoutNodes, type RankDir } from './layout'
import { exportTopologyPng } from './export-image'

// Module-scope so React Flow never sees a new nodeTypes identity per render.
const NODE_TYPES = { device: DeviceNode, lan: LanNode }

const FIT_VIEW = { padding: 0.2, maxZoom: 1.25 }

interface BuiltGraph {
  nodes: AppNode[]
  edges: Edge[]
  // Shape fingerprint: reseeding positions is needed only when this changes.
  shape: string
}

// Live overlay carried on server-derived edges. Scalars only — the selection
// panel looks the full link up by id — so the in-place patch can compare
// field-by-field like the node patch does.
interface LinkEdgeData extends Record<string, unknown> {
  operState: LinkOperState
  impaired: boolean
}

/** Interface states that POSITIVELY mean not-forwarding (Linux/RFC 2863
 * IF_OPER_*, as the server passes them through). Mirrors the backend's
 * `_DOWN_INTERFACE_STATES`: anything absent is reported unknown, never assumed
 * down, because the endpoint `state` vocabulary is an unpinned passthrough. */
const DOWN_INTERFACE_STATES = new Set(['down', 'lowerlayerdown', 'notpresent'])

/** Classify ONE endpoint for a LAN spoke's styling. The server already did this
 * for whole-link `oper_state`; a spoke needs its own member's state, so the rule
 * lives here too — keep the two in step.
 *
 * The backend has one refinement this cannot: it also reads the interface
 * `kind`, so a carrier-less `dummy` reporting "unknown" counts as up. That kind
 * is not on the wire, but it cannot arise here either — a spoke belongs to a
 * 3+-endpoint LAN, whose members are always veths attached to a bridge. Dummies
 * only appear on one-endpoint stub links, which are table-only and never drawn. */
function endpointLinkState(state: string | null): LinkOperState {
  if (state === null) return 'unknown'
  if (state === 'up') return 'up'
  return DOWN_INTERFACE_STATES.has(state) ? 'down' : 'unknown'
}

/** Stroke/animation for a link's state. Unknown reads muted-dashed, down reads
 * destructive; an impairment tints toward primary and animates — deliberately
 * distinct from health (an impaired link is doing what was asked). */
function edgeStyle(operState: LinkOperState, impaired: boolean): Partial<Edge> {
  const style: Record<string, string | number> = {}
  if (operState === 'down') style['stroke'] = 'var(--destructive)'
  else if (operState === 'degraded') style['stroke'] = 'var(--primary)'
  else if (operState === 'unknown') {
    style['stroke'] = 'var(--muted-foreground)'
    style['strokeDasharray'] = '4 3'
    style['opacity'] = 0.6
  } else if (impaired) {
    style['stroke'] = 'var(--primary)'
  }
  return { style, animated: impaired }
}

function buildGraph(
  lab: LabDetail,
  topology: ParsedTopology,
  impairedByNode: ReadonlyMap<string, number>,
  serverLinks: LabLink[] | null,
): BuiltGraph {
  const liveByName = new Map(lab.nodes.map((node) => [node.name, node]))
  const nodes: AppNode[] = []

  for (const topoNode of topology.nodes) {
    const live = liveByName.get(topoNode.name)
    nodes.push({
      id: topoNode.name,
      type: 'device',
      position: { x: 0, y: 0 },
      width: DEVICE_W,
      height: DEVICE_H,
      data: {
        label: topoNode.name,
        device: topoNode.device,
        state: live?.state ?? NOT_DEPLOYED,
        impairedIfaces: impairedByNode.get(topoNode.name) ?? 0,
      },
    })
  }

  // Reverse drift: live containers absent from the definition. Rendered
  // unlinked (never silently dropped), flagged in the card.
  const declared = new Set(topology.nodes.map((n) => n.name))
  for (const live of lab.nodes) {
    if (!declared.has(live.name)) {
      nodes.push({
        id: live.name,
        type: 'device',
        position: { x: 0, y: 0 },
        width: DEVICE_W,
        height: DEVICE_H,
        data: {
          label: live.name,
          state: live.state,
          impairedIfaces: impairedByNode.get(live.name) ?? 0,
          drifted: true,
        },
      })
    }
  }

  const edges: Edge[] = []
  if (serverLinks !== null) {
    // The server link table is the ground truth (netlab's expanded topology):
    // stable `link:<linkindex>` ids, real oper state, per-endpoint impairment.
    // Endpoint count decides the rendering — netlab's `type` is not a signal
    // (a linux-host p2p comes out "lan").
    const present = new Set(nodes.map((n) => n.id))
    for (const link of serverLinks) {
      for (const endpoint of link.endpoints) {
        // A link may reference a node the client-side parse missed — surface
        // it like the parser's implicit nodes rather than dropping the edge.
        if (!present.has(endpoint.node)) {
          present.add(endpoint.node)
          nodes.push({
            id: endpoint.node,
            type: 'device',
            position: { x: 0, y: 0 },
            width: DEVICE_W,
            height: DEVICE_H,
            data: {
              label: endpoint.node,
              state: liveByName.get(endpoint.node)?.state ?? NOT_DEPLOYED,
              impairedIfaces: impairedByNode.get(endpoint.node) ?? 0,
            },
          })
        }
      }
      if (link.endpoints.length === 2) {
        const [a, b] = link.endpoints
        if (a === undefined || b === undefined) continue
        edges.push({
          id: `link:${link.index}`,
          source: a.node,
          target: b.node,
          type: 'straight',
          data: {
            operState: link.oper_state,
            impaired: a.impairment !== null || b.impairment !== null,
          } satisfies LinkEdgeData,
          ...edgeStyle(link.oper_state, a.impairment !== null || b.impairment !== null),
        })
      } else if (link.endpoints.length > 2) {
        nodes.push({
          id: `link:${link.index}`,
          type: 'lan',
          position: { x: 0, y: 0 },
          width: LAN_W,
          height: LAN_H,
          data: { label: link.name ?? `${link.endpoints.length}-node LAN` },
        })
        for (const endpoint of link.endpoints) {
          // Each spoke carries ITS member's interface state, not the roll-up.
          const spokeState = endpointLinkState(endpoint.state)
          edges.push({
            id: `link:${link.index}~${endpoint.node}`,
            source: `link:${link.index}`,
            target: endpoint.node,
            type: 'straight',
            data: {
              operState: spokeState,
              impaired: endpoint.impairment !== null,
            } satisfies LinkEdgeData,
            ...edgeStyle(spokeState, endpoint.impairment !== null),
          })
        }
      }
      // Single-endpoint links (stubs/loopbacks) render in the table, not here.
    }
  } else {
    topology.links.forEach((link, i) => {
      if (link.kind === 'p2p') {
        edges.push({ id: `${link.a}~${link.b}#${i}`, source: link.a, target: link.b, type: 'straight' })
      } else {
        nodes.push({
          id: link.id,
          type: 'lan',
          position: { x: 0, y: 0 },
          width: LAN_W,
          height: LAN_H,
          data: { label: `${link.members.length}-node LAN` },
        })
        for (const member of link.members) {
          edges.push({ id: `${link.id}~${member}`, source: link.id, target: member, type: 'straight' })
        }
      }
    })
  }

  const shape = [
    nodes.map((n) => n.id).sort().join(','),
    edges.map((e) => e.id).join(','),
  ].join('|')
  return { nodes, edges, shape }
}

// What the bottom panel shows: a device node or a server-table link. Decoded
// from element ids (edge/hub ids are `link:<linkindex>[~member]`), the same
// pattern the builder canvas uses.
type Selection = { kind: 'node'; id: string } | { kind: 'link'; index: number }

const LINK_ID = /^link:(\d+)/

function CanvasInner({ lab, topology }: { lab: LabDetail; topology: ParsedTopology }) {
  const { resolvedTheme } = useTheme()
  const { fitView } = useReactFlow()
  const [rankdir, setRankdir] = useState<RankDir>('LR')
  const [showMiniMap, setShowMiniMap] = useState(false)
  const [selection, setSelection] = useState<Selection | null>(null)

  // Netem badge data: only running containers have a namespace to show.
  const runningNames = lab.nodes.filter((n) => n.state === 'running').map((n) => n.name)
  const netemCounts = useQueries({
    queries: runningNames.map((node) => nodeNetemQueryOptions(lab.name, node)),
    combine: (results) => {
      const counts = new Map<string, number>()
      results.forEach((result, i) => {
        const name = runningNames[i]
        if (name !== undefined && result.data !== undefined) counts.set(name, result.data.length)
      })
      return counts
    },
  })
  // combine yields a NEW Map every render; pin its identity to its content so
  // the graph memo (and the seeding effect) only fire on real changes —
  // otherwise the effect's setState re-renders into a fresh Map, forever.
  const netemKey = JSON.stringify(Array.from(netemCounts.entries()).sort())
  const impairedByNode = useMemo(
    () => netemCounts,
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed by content
    [netemKey],
  )

  // The server link table (authoritative when it resolves — including a
  // legitimately-empty one); until then, or on error, the client-side parse
  // keeps the canvas honest. Structural sharing keeps `data` referentially
  // stable across identical refetches, so the memo doesn't churn.
  const linksQuery = useQuery({
    ...labLinksQueryOptions(lab.name),
    enabled: lab.definition !== null,
  })
  const serverLinks = linksQuery.isSuccess ? linksQuery.data.links : null

  // The shared manual arrangement (delta 19), server-side and read-only here:
  // arranging happens on the Build tab (lab:edit), this canvas only renders
  // it. Structural sharing keeps `positions` referentially stable across
  // identical refetches, so another user's save re-seeds exactly once.
  const layoutQuery = useQuery(labLayoutQueryOptions(lab.name))
  const savedPositions = layoutQuery.isSuccess ? layoutQuery.data.positions : null
  const layoutSettled = !layoutQuery.isPending

  const built = useMemo(
    () => buildGraph(lab, topology, impairedByNode, serverLinks),
    [lab, topology, impairedByNode, serverLinks],
  )

  const [nodes, setNodes, onNodesChange] = useNodesState<AppNode>([])
  const [edges, setEdges] = useEdgesState<Edge>([])

  // Seed positions (dagre) only when the graph SHAPE, rank direction, or the
  // shared arrangement changes; otherwise patch node data in place so
  // live-state refreshes (SSE-driven refetches) don't reshuffle the view.
  // Seeding waits for the layout query to settle so the saved arrangement
  // applies on the FIRST paint, not as a jump after it.
  const seeded = useRef<{
    shape: string
    dir: RankDir
    positions: Record<string, { x: number; y: number }> | null
  } | null>(null)
  useEffect(() => {
    if (!layoutSettled) return
    if (
      seeded.current?.shape !== built.shape ||
      seeded.current.dir !== rankdir ||
      seeded.current.positions !== savedPositions
    ) {
      seeded.current = { shape: built.shape, dir: rankdir, positions: savedPositions }
      // Dagre places everything, then the lab's shared arrangement (saved
      // from the Build tab, delta 19) overrides the elements it knows — new
      // nodes still get sensible automatic spots, stale ids are ignored.
      const placed = layoutNodes(built.nodes, built.edges, rankdir).map((node) => {
        const saved = savedPositions?.[node.id]
        return saved ? { ...node, position: saved } : node
      })
      setNodes(placed)
      setEdges(built.edges)
      window.setTimeout(() => void fitView(FIT_VIEW), 0)
    } else {
      const fresh = new Map(built.nodes.map((n) => [n.id, n]))
      // Patch data in place, but return the SAME array when nothing changed —
      // an unconditional set here would loop (set → render → set …).
      setNodes((current) => {
        let changed = false
        const next = current.map((node) => {
          const update = fresh.get(node.id)
          if (!update) return node
          const a = node.data as Record<string, unknown>
          const b = update.data as Record<string, unknown>
          const same =
            a['label'] === b['label'] &&
            a['device'] === b['device'] &&
            a['state'] === b['state'] &&
            a['impairedIfaces'] === b['impairedIfaces'] &&
            a['drifted'] === b['drifted']
          if (same) return node
          changed = true
          return { ...node, data: update.data }
        })
        return changed ? (next as AppNode[]) : current
      })
      // Same discipline for edges: live overlay (state stroke, impairment
      // animation) refreshes in place; the array identity only changes when
      // an edge's data actually did.
      const freshEdges = new Map(built.edges.map((e) => [e.id, e]))
      setEdges((current) => {
        let changed = false
        const next = current.map((edge) => {
          const update = freshEdges.get(edge.id)
          if (!update) return edge
          const a = edge.data as LinkEdgeData | undefined
          const b = update.data as LinkEdgeData | undefined
          if (a?.operState === b?.operState && a?.impaired === b?.impaired) return edge
          changed = true
          return { ...edge, data: update.data, style: update.style, animated: update.animated }
        })
        return changed ? next : current
      })
    }
  }, [built, rankdir, layoutSettled, savedPositions, setNodes, setEdges, fitView])

  const onNodeClick: NodeMouseHandler<AppNode> = (_event, node) => {
    if (node.type === 'device') {
      setSelection({ kind: 'node', id: node.id })
      return
    }
    // A LAN hub's id IS its link id — select the link, same as its spokes.
    const hub = LINK_ID.exec(node.id)
    setSelection(hub?.[1] !== undefined ? { kind: 'link', index: Number(hub[1]) } : null)
  }

  // Server-table edges (and spokes) decode to their link; fallback-parse edges
  // carry no link identity, so clicking them just clears the selection.
  const onEdgeClick: EdgeMouseHandler<Edge> = (_event, edge) => {
    const match = LINK_ID.exec(edge.id)
    setSelection(match?.[1] !== undefined ? { kind: 'link', index: Number(match[1]) } : null)
  }

  const selectedId = selection?.kind === 'node' ? selection.id : null
  const selectedLive = selectedId !== null ? lab.nodes.find((n) => n.name === selectedId) : undefined
  const selectedData =
    selectedId !== null
      ? (nodes.find((n): n is AppNode & { type: 'device' } => n.id === selectedId && n.type === 'device')
          ?.data ?? null)
      : null
  const selectedLink =
    selection?.kind === 'link' && serverLinks !== null
      ? serverLinks.find((link) => link.index === selection.index)
      : undefined
  const can = (perm: string) => lab.permissions.includes(perm)

  return (
    <ReactFlow<AppNode>
      role="region"
      aria-label="Lab topology canvas"
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      onNodesChange={onNodesChange}
      onNodeClick={onNodeClick}
      onEdgeClick={onEdgeClick}
      onPaneClick={() => setSelection(null)}
      // Read/operate-only (maintainer's call 2026-08-03): arranging the shared
      // layout is authoring and lives on the Build tab — no dragging here.
      nodesDraggable={false}
      nodesConnectable={false}
      edgesFocusable={false}
      deleteKeyCode={null}
      snapToGrid
      snapGrid={[24, 24]}
      fitView
      fitViewOptions={FIT_VIEW}
      minZoom={0.25}
      maxZoom={2}
      colorMode={resolvedTheme === 'dark' ? 'dark' : resolvedTheme === 'light' ? 'light' : 'system'}
    >
      <Background variant={BackgroundVariant.Lines} gap={24} />
      <Controls showInteractive={false} />
      {showMiniMap && (
        <MiniMap
          pannable
          zoomable
          nodeColor={(node) =>
            node.type === 'lan'
              ? 'var(--muted)'
              : (node.data as { state?: string }).state === 'running'
                ? 'var(--primary)'
                : 'var(--muted-foreground)'
          }
        />
      )}

      <Panel position="top-right" className="flex items-center gap-1">
        <Button
          variant="outline"
          size="icon-sm"
          title={showMiniMap ? 'Hide minimap' : 'Show minimap'}
          aria-label={showMiniMap ? 'Hide minimap' : 'Show minimap'}
          data-state={showMiniMap ? 'on' : 'off'}
          className="data-[state=on]:bg-muted"
          onClick={() => setShowMiniMap((on) => !on)}
        >
          <MapIcon className="size-3.5" />
        </Button>
        <Button
          variant="outline"
          size="icon-sm"
          title="Auto-layout the view (the saved arrangement is unchanged)"
          aria-label="Auto-layout"
          onClick={() => {
            setNodes(layoutNodes(built.nodes, built.edges, rankdir))
            window.setTimeout(() => void fitView(FIT_VIEW), 0)
          }}
        >
          <LayoutGrid className="size-3.5" />
        </Button>
        <Button
          variant="outline"
          size="icon-sm"
          title={rankdir === 'LR' ? 'Rank top-to-bottom' : 'Rank left-to-right'}
          aria-label={rankdir === 'LR' ? 'Rank top-to-bottom' : 'Rank left-to-right'}
          onClick={() => setRankdir((dir) => (dir === 'LR' ? 'TB' : 'LR'))}
        >
          {rankdir === 'LR' ? <MoveVertical className="size-3.5" /> : <MoveHorizontal className="size-3.5" />}
        </Button>
        <Button
          variant="outline"
          size="icon-sm"
          title="Download PNG"
          aria-label="Download PNG"
          onClick={() => {
            void exportTopologyPng(lab.name, nodes).then((ok) =>
              ok ? toast.success('Topology exported') : toast.error('Export failed'),
            )
          }}
        >
          <Download className="size-3.5" />
        </Button>
      </Panel>

      {serverLinks === null && topology.unrendered > 0 && (
        <Panel position="top-left">
          <p className="rounded-[2px] border bg-card/90 px-2 py-1 text-xs text-muted-foreground">
            {topology.unrendered} link{topology.unrendered === 1 ? '' : 's'} not rendered —{' '}
            <Link
              to="/labs/$name/overview"
              params={{ name: lab.name }}
              className="underline hover:text-foreground"
            >
              view the definition
            </Link>
          </p>
        </Panel>
      )}

      {selectedLink !== undefined && (
        <Panel position="bottom-center" className="w-full max-w-2xl">
          <div className="flex max-h-[45vh] flex-col gap-3 overflow-y-auto rounded-[2px] border bg-card/95 px-3 py-2">
            <div className="flex items-center gap-3">
              <span className="font-mono text-sm font-medium">
                {selectedLink.name ?? `link #${selectedLink.index}`}
              </span>
              <span className="text-muted-foreground text-xs">{selectedLink.type}</span>
              {selectedLink.prefix_ipv4 !== null && (
                <span className="text-muted-foreground font-mono text-xs">
                  {selectedLink.prefix_ipv4}
                </span>
              )}
              <Badge variant={linkOperBadgeVariant(selectedLink.oper_state)}>
                {selectedLink.oper_state}
              </Badge>
            </div>
            {/* Endpoints are read-only facts; shaping them is one control
                below, bidirectional unless the user opens Advanced. */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t pt-2">
              {selectedLink.endpoints.map((endpoint) => (
                <div key={`${endpoint.node}:${endpoint.interface}`} className="flex items-center gap-2">
                  <span className="font-mono text-xs font-medium">
                    {endpoint.node}:{endpoint.interface}
                  </span>
                  {endpoint.ipv4 !== null && (
                    <span className="text-muted-foreground font-mono text-xs">{endpoint.ipv4}</span>
                  )}
                  <Badge
                    variant={
                      endpoint.state === null
                        ? 'outline'
                        : endpoint.state === 'up'
                          ? 'default'
                          : 'destructive'
                    }
                  >
                    {endpoint.state ?? 'unknown'}
                  </Badge>
                </div>
              ))}
            </div>
            <div className="border-t pt-2">
              <LinkImpairment
                name={lab.name}
                link={selectedLink}
                nodes={lab.nodes}
                canConfigure={can(PERM_LAB_CONFIGURE)}
              />
            </div>
          </div>
        </Panel>
      )}

      {selectedId !== null && selectedData !== null && (
        <Panel position="bottom-center">
          <div className="flex items-center gap-3 rounded-[2px] border bg-card/95 px-3 py-2">
            <span className="font-mono text-sm font-medium">{selectedId}</span>
            <Badge
              variant={
                selectedData.state === NOT_DEPLOYED
                  ? 'outline'
                  : nodeStateBadgeVariant(selectedData.state)
              }
            >
              {selectedData.state}
            </Badge>
            {selectedLive ? (
              <div className="flex items-center gap-1">
                <NodeConnectDrawer
                  name={lab.name}
                  node={selectedLive}
                  canRead={can(PERM_LAB_READ)}
                  canTerminal={can(PERM_LAB_TERMINAL)}
                />
                <NodeControls
                  name={lab.name}
                  node={selectedLive.name}
                  state={selectedLive.state}
                  canConfigure={can(PERM_LAB_CONFIGURE)}
                  canRead={can(PERM_LAB_READ)}
                  canTerminal={can(PERM_LAB_TERMINAL)}
                />
              </div>
            ) : (
              <span className="text-xs text-muted-foreground">
                Not deployed — no runtime actions.
              </span>
            )}
          </div>
        </Panel>
      )}
    </ReactFlow>
  )
}

/** Read-only topology canvas: the parsed definition laid out by dagre, live
 * node state and netem badges overlaid, quick actions on selection. */
export function TopologyCanvas({ lab, topology }: { lab: LabDetail; topology: ParsedTopology }) {
  return (
    <ReactFlowProvider>
      <CanvasInner lab={lab} topology={topology} />
    </ReactFlowProvider>
  )
}
