import dagre from '@dagrejs/dagre'
import type { Edge } from '@xyflow/react'

import { DEVICE_H, DEVICE_W, LAN_H, LAN_W, type AppNode } from './flow-types'

export type RankDir = 'LR' | 'TB'

/** Dagre auto-layout over the fixed node geometry. Spacing rides the identity
 * grid (24px multiples); dagre yields centers, React Flow wants top-left. */
export function layoutNodes(nodes: AppNode[], edges: Edge[], rankdir: RankDir): AppNode[] {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir, nodesep: 48, ranksep: 72 })
  g.setDefaultEdgeLabel(() => ({}))

  for (const node of nodes) {
    const isLan = node.type === 'lan'
    g.setNode(node.id, { width: isLan ? LAN_W : DEVICE_W, height: isLan ? LAN_H : DEVICE_H })
  }
  // Self-links carry no ranking information and dagre would inflate the
  // layout around them; their node is placed by its other edges.
  for (const edge of edges) {
    if (edge.source !== edge.target) g.setEdge(edge.source, edge.target)
  }
  dagre.layout(g)

  return nodes.map((node) => {
    const placed = g.node(node.id)
    return {
      ...node,
      position: { x: placed.x - placed.width / 2, y: placed.y - placed.height / 2 },
    }
  })
}
