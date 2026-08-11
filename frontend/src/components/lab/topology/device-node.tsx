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
 * the schematic look without floating-edge math. Ids let the builder pin its
 * edges deterministically; id-less edges (the read-only canvas) resolve to
 * these same handles because they register first. */
export function CenterHandles({ isConnectable }: { isConnectable?: boolean }) {
  const style = { left: '50%', top: '50%', opacity: 0, pointerEvents: 'none' as const }
  return (
    <>
      <Handle id="c-s" type="source" position={Position.Top} style={style} isConnectable={isConnectable} />
      <Handle id="c-t" type="target" position={Position.Top} style={style} isConnectable={isConnectable} />
    </>
  )
}

/** The builder's drag-to-connect grip: a source handle on the node's right
 * edge, present only when the canvas is connectable (the read-only topology
 * view passes nodesConnectable={false} and renders no grip). Drops land on
 * the invisible center target via the canvas's connectionRadius.
 *
 * The HIT AREA and the dot are deliberately different sizes: a 10px target
 * that only appears on hover is a game of darts, so the handle itself is a
 * transparent 24px square and the visible dot is a non-interactive child
 * inside it. It also stays lit while the node is selected — after a click you
 * already know which node you are working on, and that is when you reach for
 * the wire. */
export function ConnectGrip({
  isConnectable,
  selected,
}: {
  isConnectable?: boolean
  selected?: boolean
}) {
  if (isConnectable !== true) return null
  return (
    <Handle
      id="drag"
      type="source"
      position={Position.Right}
      isConnectable
      className={cn(
        '!flex !size-6 !items-center !justify-center !rounded-full !border-0 !bg-transparent transition-opacity group-hover:opacity-100',
        selected === true ? 'opacity-100' : 'opacity-0',
      )}
      title="drag to connect"
    >
      <span className="pointer-events-none size-2.5 rounded-full border border-background bg-primary" />
    </Handle>
  )
}

export function DeviceNode({ data, selected, isConnectable }: NodeProps<DeviceFlowNode>) {
  const notDeployed = data.state === NOT_DEPLOYED
  const running = data.state === 'running'
  return (
    <div
      style={{ width: DEVICE_W, height: DEVICE_H }}
      className={cn(
        'group relative flex items-center gap-2 rounded-[2px] border border-(--tp-node-border) bg-card px-3',
        notDeployed && 'border-dashed text-muted-foreground',
        selected && 'ring-2 ring-primary',
      )}
    >
      <CenterHandles isConnectable={isConnectable} />
      <ConnectGrip isConnectable={isConnectable} selected={selected} />
      <DeviceGlyph device={data.device} />
      <div className="flex min-w-0 flex-col">
        <span className="truncate font-mono text-sm font-medium">{data.label}</span>
        <span className="truncate text-[0.65rem] text-muted-foreground">
          {data.drifted
            ? 'not in definition'
            : data.fromComponent !== undefined
              ? `from ${data.fromComponent}`
              : (data.device ?? '—')}
        </span>
      </div>
      <span
        aria-label={`state: ${data.state}`}
        className={cn(
          'absolute right-2 bottom-2 size-1.5 rounded-full',
          running ? 'bg-primary' : notDeployed ? 'border border-muted-foreground' : 'bg-muted-foreground',
        )}
      />
      {data.groups !== undefined && data.groups.length > 0 && (
        <span className="absolute -top-1 left-2 flex gap-1">
          {data.groups.map((group) => (
            <span
              key={group.name}
              title={`group: ${group.name}`}
              aria-label={`group: ${group.name}`}
              style={{ backgroundColor: group.color }}
              className="size-2 rounded-full border border-background"
            />
          ))}
        </span>
      )}
      {data.impairedIfaces > 0 && (
        <span
          title={`${data.impairedIfaces} impaired interface(s)`}
          className="absolute -top-2 -right-2 flex items-center gap-0.5 rounded-[2px] border border-(--tp-node-border) bg-card px-1 font-mono text-[0.6rem] text-primary"
        >
          <Zap className="size-3" />
          {data.impairedIfaces}
        </span>
      )}
    </div>
  )
}
