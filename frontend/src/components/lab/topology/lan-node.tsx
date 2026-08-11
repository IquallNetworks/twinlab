import { type NodeProps } from '@xyflow/react'
import { Waypoints } from 'lucide-react'

import { LAN_H, LAN_W, type LanFlowNode } from './flow-types'

import { CenterHandles, ConnectGrip } from './device-node'

/** A multi-access link (3+ endpoints) drawn as a hub pseudo-node. */
export function LanNode({ data, isConnectable }: NodeProps<LanFlowNode>) {
  return (
    <div
      style={{ width: LAN_W, height: LAN_H }}
      className="group relative flex flex-col items-center justify-center gap-0.5 rounded-[2px] border border-dashed border-(--tp-node-border) bg-muted text-muted-foreground"
      title={data.label}
    >
      <CenterHandles isConnectable={isConnectable} />
      <ConnectGrip isConnectable={isConnectable} />
      <Waypoints className="size-4" />
      <span className="font-mono text-[0.55rem] tracking-wide uppercase">lan</span>
      {data.prefix !== undefined && (
        <span className="pointer-events-none absolute top-full left-1/2 mt-1 -translate-x-1/2 font-mono text-[0.6rem] whitespace-nowrap text-muted-foreground">
          {data.prefix}
        </span>
      )}
    </div>
  )
}
