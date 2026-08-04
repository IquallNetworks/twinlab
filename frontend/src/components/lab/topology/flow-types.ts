import type { Node } from '@xyflow/react'

// Typed React Flow v12 node union for the topology canvas.

export interface DeviceNodeData {
  label: string
  device?: string
  // Docker-vocabulary runtime state, or 'not-deployed' for a definition node
  // with no live container (fresh, destroyed, or definition drift).
  state: string
  // Actively-impaired interface count (netem) — 0 hides the badge.
  impairedIfaces: number
  // Live container that is NOT in the definition (definition edited after
  // deploy) — rendered unlinked rather than silently dropped.
  drifted?: boolean
  // Group memberships as colored dots (delta 20; the builder canvas sets
  // this — a node can be in several groups, so dots beat a tinted border).
  groups?: { name: string; color: string }[]
  [key: string]: unknown
}

export type DeviceFlowNode = Node<DeviceNodeData, 'device'>
export type LanFlowNode = Node<{ label: string; [key: string]: unknown }, 'lan'>
// A one-endpoint (stub/loopback) link, drawn as a small terminator so it is
// selectable and deletable — invisible data can't be edited. Builder-only.
export type StubFlowNode = Node<{ label: string; [key: string]: unknown }, 'stub'>
export type AppNode = DeviceFlowNode | LanFlowNode | StubFlowNode

export const NOT_DEPLOYED = 'not-deployed'

// A manual arrangement: canvas element id -> position. Persisted server-side
// per lab (delta 19, `GET/PUT /labs/{name}/layout`) and shared across users;
// the Build tab is the only writer (lab:edit) — other canvases read.
export type SavedPositions = Record<string, { x: number; y: number }>

// Fixed node geometry: the components render at exactly these sizes, so dagre
// and React Flow's fitView are deterministic (no measure-then-jitter frame).
export const DEVICE_W = 156
export const DEVICE_H = 56
export const LAN_W = 48
export const LAN_H = 48
export const STUB_W = 40
export const STUB_H = 40
