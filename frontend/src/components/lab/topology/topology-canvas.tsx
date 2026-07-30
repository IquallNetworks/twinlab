import { useQueries } from '@tanstack/react-query'
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
  type NodeMouseHandler,
} from '@xyflow/react'
import { Download, LayoutGrid, Map as MapIcon, MoveHorizontal, MoveVertical } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTheme } from 'next-themes'
import { toast } from 'sonner'

import { NodeConnectDrawer } from '@/components/lab/node-connect-drawer'
import { NodeControls } from '@/components/lab/node-controls'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { nodeStateBadgeVariant } from '@/lib/format'
import {
  PERM_LAB_CONFIGURE,
  PERM_LAB_READ,
  PERM_LAB_TERMINAL,
} from '@/lib/lab-permissions'
import { nodeNetemQueryOptions } from '@/lib/queries'
import type { LabDetail } from '@/lib/schemas'
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
import { clearLayout, loadLayout, saveLayout } from './layout-store'
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

function buildGraph(
  lab: LabDetail,
  topology: ParsedTopology,
  impairedByNode: ReadonlyMap<string, number>,
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

  const shape = [
    nodes.map((n) => n.id).sort().join(','),
    edges.map((e) => e.id).join(','),
  ].join('|')
  return { nodes, edges, shape }
}

function CanvasInner({ lab, topology }: { lab: LabDetail; topology: ParsedTopology }) {
  const { resolvedTheme } = useTheme()
  const { fitView } = useReactFlow()
  const [rankdir, setRankdir] = useState<RankDir>('LR')
  const [showMiniMap, setShowMiniMap] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)

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

  const built = useMemo(
    () => buildGraph(lab, topology, impairedByNode),
    [lab, topology, impairedByNode],
  )

  const [nodes, setNodes, onNodesChange] = useNodesState<AppNode>([])
  const [edges, setEdges] = useEdgesState<Edge>([])

  // Seed positions (dagre) only when the graph SHAPE or rank direction
  // changes; otherwise patch node data in place so live-state refreshes
  // (SSE-driven refetches) don't blow away the user's drags.
  const seeded = useRef<{ shape: string; dir: RankDir } | null>(null)
  useEffect(() => {
    if (seeded.current?.shape !== built.shape || seeded.current.dir !== rankdir) {
      seeded.current = { shape: built.shape, dir: rankdir }
      // Dagre places everything, then the user's saved manual layout (drag
      // to arrange; persisted per lab in this browser) overrides the nodes
      // it knows — new nodes still get sensible automatic spots.
      const savedPositions = loadLayout(lab.name)
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
    }
  }, [built, rankdir, lab.name, setNodes, setEdges, fitView])

  // Mirror for event handlers: drag-stop needs the freshest node set even if
  // the final position change lands in the same batch.
  const nodesRef = useRef(nodes)
  nodesRef.current = nodes

  const onNodeClick: NodeMouseHandler<AppNode> = (_event, node) => {
    setSelectedId(node.type === 'device' ? node.id : null)
  }

  const selectedLive = selectedId !== null ? lab.nodes.find((n) => n.name === selectedId) : undefined
  const selectedData =
    selectedId !== null
      ? (nodes.find((n): n is AppNode & { type: 'device' } => n.id === selectedId && n.type === 'device')
          ?.data ?? null)
      : null
  const can = (perm: string) => lab.permissions.includes(perm)

  return (
    <ReactFlow<AppNode>
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      onNodesChange={onNodesChange}
      onNodeClick={onNodeClick}
      onNodeDragStop={(_event, _node, dragged) => {
        // Dragging IS defining the manual layout: persist it per lab.
        const merged = nodesRef.current.map((node) => {
          const moved = dragged.find((d) => d.id === node.id)
          return moved ? { ...node, position: moved.position } : node
        })
        saveLayout(lab.name, merged as AppNode[])
      }}
      onPaneClick={() => setSelectedId(null)}
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
          data-state={showMiniMap ? 'on' : 'off'}
          className="data-[state=on]:bg-muted"
          onClick={() => setShowMiniMap((on) => !on)}
        >
          <MapIcon className="size-3.5" />
        </Button>
        <Button
          variant="outline"
          size="icon-sm"
          title="Auto-layout (clears your manual layout)"
          onClick={() => {
            clearLayout(lab.name)
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
          onClick={() => setRankdir((dir) => (dir === 'LR' ? 'TB' : 'LR'))}
        >
          {rankdir === 'LR' ? <MoveVertical className="size-3.5" /> : <MoveHorizontal className="size-3.5" />}
        </Button>
        <Button
          variant="outline"
          size="icon-sm"
          title="Download PNG"
          onClick={() => {
            void exportTopologyPng(lab.name, nodes).then((ok) =>
              ok ? toast.success('Topology exported') : toast.error('Export failed'),
            )
          }}
        >
          <Download className="size-3.5" />
        </Button>
      </Panel>

      {topology.unrendered > 0 && (
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
                  running={selectedLive.state === 'running'}
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
