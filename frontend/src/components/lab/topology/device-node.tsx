import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Network, Router, Server, Zap } from 'lucide-react'

import { cn } from '@/lib/utils'

import { DEVICE_H, DEVICE_W, NOT_DEPLOYED, type DeviceFlowNode } from './flow-types'

// Hosts run plain images; everything else in netlab is router-shaped enough.
const HOST_DEVICES = new Set(['linux', 'host'])

function DeviceGlyph({ device }: { device?: string }) {
  if (device === undefined) return <Network className="size-4" />
  if (HOST_DEVICES.has(device)) return <Server className="size-4" />
  return <Router className="size-4" />
}

/** Wires attach invisibly at the node center: with straight edges the line is
 * occluded by the opaque body and visually meets the border from any angle —
 * the schematic look without floating-edge math. */
function CenterHandles() {
  const style = { left: '50%', top: '50%', opacity: 0, pointerEvents: 'none' as const }
  return (
    <>
      <Handle type="source" position={Position.Top} style={style} />
      <Handle type="target" position={Position.Top} style={style} />
    </>
  )
}

export function DeviceNode({ data, selected }: NodeProps<DeviceFlowNode>) {
  const notDeployed = data.state === NOT_DEPLOYED
  const running = data.state === 'running'
  return (
    <div
      style={{ width: DEVICE_W, height: DEVICE_H }}
      className={cn(
        'relative flex items-center gap-2 rounded-[2px] border bg-card px-3',
        notDeployed && 'border-dashed text-muted-foreground',
        selected && 'ring-2 ring-primary',
      )}
    >
      <CenterHandles />
      <DeviceGlyph device={data.device} />
      <div className="flex min-w-0 flex-col">
        <span className="truncate font-mono text-sm font-medium">{data.label}</span>
        <span className="truncate text-[0.65rem] text-muted-foreground">
          {data.drifted ? 'not in definition' : (data.device ?? '—')}
        </span>
      </div>
      <span
        aria-label={`state: ${data.state}`}
        className={cn(
          'absolute right-2 bottom-2 size-1.5 rounded-full',
          running ? 'bg-primary' : notDeployed ? 'border border-muted-foreground' : 'bg-muted-foreground',
        )}
      />
      {data.impairedIfaces > 0 && (
        <span
          title={`${data.impairedIfaces} impaired interface(s)`}
          className="absolute -top-2 -right-2 flex items-center gap-0.5 rounded-[2px] border bg-card px-1 font-mono text-[0.6rem] text-primary"
        >
          <Zap className="size-3" />
          {data.impairedIfaces}
        </span>
      )}
    </div>
  )
}
