import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from '@xyflow/react'

import { DEVICE_H } from './flow-types'

// How far above the node body the loop reaches. The node is opaque and edges
// render beneath it, so the arc only shows past the top border — the same way
// straight edges meet the border instead of the center.
const RISE = DEVICE_H / 2 + 44
const SPREAD = 56

/** A link whose two endpoints are the SAME node (netlab gives it two
 * interfaces on one link). Both connection handles sit at the node center, so
 * there is no direction to derive a path from — this draws a fixed loop out of
 * the node's top instead of the zero-length line a straight edge would give. */
export function SelfLoopEdge({ id, sourceX, sourceY, label, markerEnd, style }: EdgeProps) {
  const top = sourceY - RISE
  const path = `M ${sourceX} ${sourceY} C ${sourceX - SPREAD} ${top} ${sourceX + SPREAD} ${top} ${sourceX} ${sourceY}`
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />
      {label !== undefined && label !== null && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${sourceX}px, ${top + RISE / 6}px)`,
            }}
            className="pointer-events-none rounded-[2px] bg-card px-1 font-mono text-[0.65rem]"
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
