import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Waypoints } from 'lucide-react'

import { LAN_H, LAN_W, type LanFlowNode } from './flow-types'

/** A multi-access link (3+ endpoints) drawn as a hub pseudo-node. */
export function LanNode({ data }: NodeProps<LanFlowNode>) {
  const style = { left: '50%', top: '50%', opacity: 0, pointerEvents: 'none' as const }
  return (
    <div
      style={{ width: LAN_W, height: LAN_H }}
      className="flex flex-col items-center justify-center gap-0.5 rounded-[2px] border border-dashed bg-muted/60 text-muted-foreground"
      title={data.label}
    >
      <Handle type="source" position={Position.Top} style={style} />
      <Handle type="target" position={Position.Top} style={style} />
      <Waypoints className="size-4" />
      <span className="font-mono text-[0.55rem] tracking-wide uppercase">lan</span>
    </div>
  )
}
