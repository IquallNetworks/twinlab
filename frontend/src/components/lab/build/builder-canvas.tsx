import {
  Background,
  BackgroundVariant,
  ConnectionLineType,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type OnSelectionChangeParams,
  type XYPosition,
} from '@xyflow/react'
import { LayoutGrid, Map as MapIcon, MoveHorizontal, MoveVertical } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type Dispatch } from 'react'
import { useTheme } from 'next-themes'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { nextLanId, nextNodeName, type BuildDoc } from '@/lib/build-doc'
import type { CatalogDevice } from '@/lib/device-catalog'

import { DeviceNode } from '../topology/device-node'
import {
  DEVICE_H,
  DEVICE_W,
  LAN_H,
  LAN_W,
  NOT_DEPLOYED,
  type AppNode,
} from '../topology/flow-types'
import { LanNode } from '../topology/lan-node'
import { layoutNodes, type RankDir } from '../topology/layout'
import type { SavedPositions } from '../topology/flow-types'

import { validateConnect, type BuilderAction, type BuilderState, type Selection } from './build-state'
import { BuilderPalette } from './builder-palette'

// Module-scope so React Flow never sees a new nodeTypes identity per render.
const NODE_TYPES = { device: DeviceNode, lan: LanNode }

const FIT_VIEW = { padding: 0.2, maxZoom: 1.25 }
const GRID = 24

// Edge ids carry their doc coordinates ('|' never appears in node names or
// lan ids, so splitting is unambiguous): a p2p link is `link|<index>`, a LAN
// membership is `member|<lanId>|<node>`.
const p2pEdgeId = (index: number) => `link|${index}`
const memberEdgeId = (lanId: string, node: string) => `member|${lanId}|${node}`

interface BuilderCanvasProps {
  state: BuilderState
  dispatch: Dispatch<BuilderAction>
  positions: SavedPositions
  // persist=true writes through to the per-lab layout store (drag end,
  // palette add, auto-layout); transient bookkeeping passes false.
  onPositions: (next: SavedPositions, persist: boolean) => void
}

function sameSelection(a: Selection, b: Selection): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

/** The doc rendered as React Flow structure — positions and selection are
 * deliberately NOT here: React Flow owns them (applyNodeChanges), the sync
 * effect below carries them across doc changes. */
function graphFromDoc(doc: BuildDoc): { nodes: AppNode[]; edges: Edge[] } {
  const nodes: AppNode[] = doc.nodes.map((node) => ({
    id: node.name,
    type: 'device',
    position: { x: 0, y: 0 },
    width: DEVICE_W,
    height: DEVICE_H,
    data: {
      label: node.name,
      device: node.device ?? doc.defaultDevice,
      state: NOT_DEPLOYED,
      impairedIfaces: 0,
    },
  }))

  const edges: Edge[] = []
  doc.links.forEach((link, index) => {
    if (link.kind === 'p2p') {
      edges.push({
        id: p2pEdgeId(index),
        source: link.a,
        target: link.b,
        sourceHandle: 'c-s',
        targetHandle: 'c-t',
        type: 'straight',
      })
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
        edges.push({
          id: memberEdgeId(link.id, member),
          source: link.id,
          target: member,
          sourceHandle: 'c-s',
          targetHandle: 'c-t',
          type: 'straight',
        })
      }
    }
  })

  return { nodes, edges }
}

function CanvasInner({ state, dispatch, positions, onPositions }: BuilderCanvasProps) {
  const { resolvedTheme } = useTheme()
  const { fitView, screenToFlowPosition } = useReactFlow()
  const [rankdir, setRankdir] = useState<RankDir>('LR')
  const [showMiniMap, setShowMiniMap] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const doc = state.doc

  const graph = useMemo(() => graphFromDoc(doc), [doc])

  // React Flow owns the interactive node state (positions, selection,
  // measurements) through the hooks' built-in applyNodeChanges — a fully
  // hand-controlled array here loops: unapplied select/dimension changes get
  // re-emitted against every wholesale-replaced array.
  const [nodes, setNodes, onNodesChange] = useNodesState<AppNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  const nodesRef = useRef(nodes)
  nodesRef.current = nodes
  const positionsRef = useRef(positions)
  positionsRef.current = positions
  const onPositionsRef = useRef(onPositions)
  onPositionsRef.current = onPositions
  const rankdirRef = useRef(rankdir)
  rankdirRef.current = rankdir
  const selectionRef = useRef(state.selection)
  selectionRef.current = state.selection
  const firstFit = useRef(true)

  // Sync doc → canvas whenever the doc changes: existing nodes keep their
  // position/selection (only data is patched), new nodes take their saved or
  // palette-drop spot, and anything unknown gets a dagre placement computed
  // over the whole graph (also written back to the positions map so renames
  // can migrate it later).
  useEffect(() => {
    const byId = new Map(nodesRef.current.map((node) => [node.id, node]))
    const unplaced = graph.nodes.filter(
      (node) => !byId.has(node.id) && positionsRef.current[node.id] === undefined,
    )
    let placed: Map<string, XYPosition> | null = null
    if (unplaced.length > 0) {
      placed = new Map(
        layoutNodes(graph.nodes, graph.edges, rankdirRef.current).map((node) => [
          node.id,
          node.position,
        ]),
      )
      const filled = { ...positionsRef.current }
      for (const node of unplaced) {
        const spot = placed.get(node.id)
        if (spot !== undefined) filled[node.id] = spot
      }
      onPositionsRef.current(filled, false)
    }
    setNodes(
      graph.nodes.map((node) => {
        const existing = byId.get(node.id)
        // Ids are unique across node kinds, so existing and node share a
        // type; the spread just can't prove it across the union.
        if (existing !== undefined) return { ...existing, data: node.data } as AppNode
        return {
          ...node,
          position: positionsRef.current[node.id] ?? placed?.get(node.id) ?? { x: 0, y: 0 },
        }
      }),
    )
    setEdges((current) => {
      const selected = new Set(current.filter((edge) => edge.selected === true).map((e) => e.id))
      return graph.edges.map((edge) => (selected.has(edge.id) ? { ...edge, selected: true } : edge))
    })
    if (firstFit.current) {
      firstFit.current = false
      window.setTimeout(() => void fitView(FIT_VIEW), 0)
    }
  }, [graph, setNodes, setEdges, fitView])

  const persistCurrentPositions = (dragged?: readonly AppNode[]) => {
    const merged: SavedPositions = { ...positionsRef.current }
    for (const node of nodesRef.current) merged[node.id] = node.position
    for (const node of dragged ?? []) merged[node.id] = node.position
    onPositionsRef.current(merged, true)
  }

  const dropPosition = (): XYPosition => {
    const rect = wrapperRef.current?.getBoundingClientRect()
    const center =
      rect !== undefined && rect !== null
        ? screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 })
        : { x: 0, y: 0 }
    const stagger = (doc.nodes.length + doc.links.length) % 5
    return {
      x: Math.round((center.x + stagger * GRID) / GRID) * GRID,
      y: Math.round((center.y + stagger * GRID) / GRID) * GRID,
    }
  }

  const addDevice = (device: CatalogDevice) => {
    const name = nextNodeName(doc, device.device)
    onPositions({ ...positionsRef.current, [name]: dropPosition() }, true)
    dispatch({ type: 'add-node', name, device: device.device })
  }

  const addLan = () => {
    const id = nextLanId(doc)
    onPositions({ ...positionsRef.current, [id]: dropPosition() }, true)
    dispatch({ type: 'add-lan', id })
  }

  const onConnect = (connection: Connection) => {
    const verdict = validateConnect(doc, connection.source, connection.target)
    if (verdict.ok) dispatch({ type: 'connect', source: connection.source, target: connection.target })
    else toast.error(verdict.reason)
  }

  // React Flow drives selection (the hooks apply its select changes); this
  // only mirrors it into the builder state for the inspector. Empty
  // selections are ignored — they also fire spuriously when the node set is
  // rebuilt — deselection is the pane click below.
  const onSelectionChange = ({ nodes: selNodes, edges: selEdges }: OnSelectionChangeParams) => {
    let next: Selection | null = null
    const node = selNodes[0]
    const edge = selEdges[0]
    if (node !== undefined) {
      if (node.type === 'device') {
        next = { kind: 'node', name: node.id }
      } else {
        const linkIndex = doc.links.findIndex((link) => link.kind === 'lan' && link.id === node.id)
        if (linkIndex >= 0) next = { kind: 'lan', linkIndex }
      }
    } else if (edge !== undefined) {
      const [tag, first, second] = edge.id.split('|')
      if (tag === 'link' && first !== undefined) {
        const linkIndex = Number(first)
        if (doc.links[linkIndex]?.kind === 'p2p') next = { kind: 'link', linkIndex }
      } else if (tag === 'member' && first !== undefined && second !== undefined) {
        const linkIndex = doc.links.findIndex((link) => link.kind === 'lan' && link.id === first)
        if (linkIndex >= 0) next = { kind: 'member', linkIndex, node: second }
      }
    }
    if (next !== null && !sameSelection(selectionRef.current, next)) {
      dispatch({ type: 'select', selection: next })
    }
  }

  const onDelete = ({ nodes: delNodes, edges: delEdges }: { nodes: AppNode[]; edges: Edge[] }) => {
    // Order matters: link indices are positional in the doc. Membership
    // removals don't reshape the array, so they go first; then p2p/LAN link
    // deletions in DESCENDING index order (earlier removals can't shift the
    // later ones); node deletions are by name and cascade on their own.
    const memberRemovals: { linkIndex: number; node: string }[] = []
    const linkDeletions: number[] = []
    for (const edge of delEdges) {
      const [tag, first, second] = edge.id.split('|')
      if (tag === 'link' && first !== undefined) {
        linkDeletions.push(Number(first))
      } else if (tag === 'member' && first !== undefined && second !== undefined) {
        const linkIndex = doc.links.findIndex((link) => link.kind === 'lan' && link.id === first)
        if (linkIndex >= 0) memberRemovals.push({ linkIndex, node: second })
      }
    }
    const nodeDeletions: string[] = []
    for (const node of delNodes) {
      if (node.type === 'device') {
        nodeDeletions.push(node.id)
      } else {
        const linkIndex = doc.links.findIndex((link) => link.kind === 'lan' && link.id === node.id)
        if (linkIndex >= 0) linkDeletions.push(linkIndex)
      }
    }
    for (const removal of memberRemovals) dispatch({ type: 'remove-member', ...removal })
    for (const linkIndex of [...new Set(linkDeletions)].sort((a, b) => b - a)) {
      dispatch({ type: 'delete-link', linkIndex })
    }
    for (const name of nodeDeletions) dispatch({ type: 'delete-node', name })
  }

  const applyLayout = (dir: RankDir) => {
    const placed = new Map(
      layoutNodes(graph.nodes, graph.edges, dir).map((node) => [node.id, node.position]),
    )
    setNodes((current) =>
      current.map((node) => {
        const spot = placed.get(node.id)
        return spot !== undefined ? { ...node, position: spot } : node
      }),
    )
    const next: SavedPositions = {}
    for (const [id, spot] of placed) next[id] = spot
    onPositionsRef.current(next, true)
    window.setTimeout(() => void fitView(FIT_VIEW), 0)
  }

  return (
    <div ref={wrapperRef} role="region" aria-label="Topology builder canvas" className="h-full w-full">
      <ReactFlow<AppNode>
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeDragStop={(_event, _node, dragged) => persistCurrentPositions(dragged)}
        onConnect={onConnect}
        isValidConnection={(connection) =>
          validateConnect(doc, connection.source, connection.target).ok
        }
        onSelectionChange={onSelectionChange}
        onPaneClick={() => {
          if (selectionRef.current.kind !== 'lab') {
            dispatch({ type: 'select', selection: { kind: 'lab' } })
          }
        }}
        onDelete={onDelete}
        deleteKeyCode={['Backspace', 'Delete']}
        connectionLineType={ConnectionLineType.Straight}
        connectionRadius={80}
        snapToGrid
        snapGrid={[GRID, GRID]}
        fitView
        fitViewOptions={FIT_VIEW}
        minZoom={0.25}
        maxZoom={2}
        colorMode={resolvedTheme === 'dark' ? 'dark' : resolvedTheme === 'light' ? 'light' : 'system'}
      >
        <Background variant={BackgroundVariant.Lines} gap={GRID} />
        <Controls showInteractive={false} />
        {showMiniMap && (
          <MiniMap
            pannable
            zoomable
            nodeColor={(node) => (node.type === 'lan' ? 'var(--muted)' : 'var(--muted-foreground)')}
          />
        )}

        <BuilderPalette onAddDevice={addDevice} onAddLan={addLan} />

        {/* Teaching overlay: gone the moment the first node lands. */}
        {doc.nodes.length === 0 && (
          <Panel position="top-center" className="pointer-events-none mt-14">
            <div className="max-w-sm rounded-[2px] border bg-card/90 px-4 py-3 text-center">
              <p className="font-mono text-xs tracking-wide text-muted-foreground uppercase">
                blank canvas
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                <span className="font-medium text-foreground">Add</span> a device from the menu,
                drag between nodes to connect them, then{' '}
                <span className="font-medium text-foreground">Save</span> — deploying applies the
                saved definition.
              </p>
            </div>
          </Panel>
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
            title="Auto-layout (replaces your manual layout)"
            aria-label="Auto-layout"
            onClick={() => applyLayout(rankdir)}
          >
            <LayoutGrid className="size-3.5" />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            title={rankdir === 'LR' ? 'Rank top-to-bottom' : 'Rank left-to-right'}
            aria-label={rankdir === 'LR' ? 'Rank top-to-bottom' : 'Rank left-to-right'}
            onClick={() => {
              const next: RankDir = rankdir === 'LR' ? 'TB' : 'LR'
              setRankdir(next)
              applyLayout(next)
            }}
          >
            {rankdir === 'LR' ? <MoveVertical className="size-3.5" /> : <MoveHorizontal className="size-3.5" />}
          </Button>
        </Panel>
      </ReactFlow>
    </div>
  )
}

/** The editable canvas: structure derives from the BuildDoc (the reducer owns
 * the truth), React Flow owns positions/selection, and the shared per-lab
 * layout store carries manual arrangements between the Build tab and
 * Overview's topology view. Every edit dispatches an action. */
export function BuilderCanvas(props: BuilderCanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  )
}
