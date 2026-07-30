import type { AppNode } from './flow-types'

// Manual topology layouts, persisted per lab in localStorage (this browser
// only). Server-side persistence — a layout shared across users — needs a
// field on the lab record: a parked backend item (docs/frontend-rework.md).

export type SavedPositions = Record<string, { x: number; y: number }>

const keyFor = (lab: string) => `twinlab.topology.layout.${lab}`

export function loadLayout(lab: string): SavedPositions | null {
  const raw = localStorage.getItem(keyFor(lab))
  if (raw === null) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null
    const positions: SavedPositions = {}
    for (const [id, pos] of Object.entries(parsed)) {
      if (
        typeof pos === 'object' &&
        pos !== null &&
        typeof (pos as { x?: unknown }).x === 'number' &&
        typeof (pos as { y?: unknown }).y === 'number'
      ) {
        positions[id] = { x: (pos as { x: number }).x, y: (pos as { y: number }).y }
      }
    }
    return positions
  } catch {
    return null
  }
}

export function saveLayout(lab: string, nodes: readonly AppNode[]): void {
  const positions: SavedPositions = {}
  for (const node of nodes) positions[node.id] = { x: node.position.x, y: node.position.y }
  localStorage.setItem(keyFor(lab), JSON.stringify(positions))
}

export function clearLayout(lab: string): void {
  localStorage.removeItem(keyFor(lab))
}
