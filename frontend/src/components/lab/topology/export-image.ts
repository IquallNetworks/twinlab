import { getNodesBounds, getViewportForBounds, type Node } from '@xyflow/react'
import { toPng } from 'html-to-image'

// Fixed export framing: viewport-independent, wide enough for real cores.
const EXPORT_W = 1600
const EXPORT_H = 900

/** Render the canvas to a PNG and trigger a download. The official React Flow
 * recipe: frame ALL nodes (not the current viewport) and rasterize the
 * viewport element with html-to-image. */
export async function exportTopologyPng(labName: string, nodes: Node[]): Promise<boolean> {
  const viewport = document.querySelector<HTMLElement>('.react-flow__viewport')
  if (!viewport || nodes.length === 0) return false

  const bounds = getNodesBounds(nodes)
  const { x, y, zoom } = getViewportForBounds(bounds, EXPORT_W, EXPORT_H, 0.25, 2, 0.1)
  const background =
    getComputedStyle(document.documentElement).getPropertyValue('--background').trim() || '#ffffff'

  try {
    const dataUrl = await toPng(viewport, {
      backgroundColor: background,
      width: EXPORT_W,
      height: EXPORT_H,
      style: {
        width: `${EXPORT_W}px`,
        height: `${EXPORT_H}px`,
        transform: `translate(${x}px, ${y}px) scale(${zoom})`,
      },
    })
    const a = document.createElement('a')
    a.href = dataUrl
    a.download = `${labName}-topology.png`
    a.click()
    return true
  } catch {
    return false
  }
}
