import { type NodeProps } from '@xyflow/react'
import { CircleDot } from 'lucide-react'

import { STUB_H, STUB_W, type StubFlowNode } from './flow-types'

import { CenterHandles } from './device-node'

/** A stub link (one endpoint — netlab resolves it to a loopback/dummy
 * interface) drawn as a small terminator hanging off its node. Handles exist
 * only so its edge can attach; a stub never connects to anything else. */
export function StubNode({ data }: NodeProps<StubFlowNode>) {
  return (
    <div
      style={{ width: STUB_W, height: STUB_H }}
      className="group relative flex flex-col items-center justify-center gap-0.5 rounded-[2px] border border-dotted border-(--tp-node-border) bg-muted/60 text-muted-foreground"
      title={data.label}
    >
      <CenterHandles isConnectable={false} />
      <CircleDot className="size-3.5" />
      <span className="font-mono text-[0.5rem] tracking-wide uppercase">stub</span>
    </div>
  )
}
