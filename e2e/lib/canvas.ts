import type { Locator, Page } from '@playwright/test'

// React Flow canvases (the Overview topology view and the Build tab's builder).
// Nodes are .react-flow__node elements; edges .react-flow__edge. `canvas` is
// the region locator (aria-label "Lab topology canvas" / "Topology builder
// canvas").

// React Flow stamps the node id as data-id ("r1", "lan:1", "stub:1", …) —
// exact, unlike text filtering (hasText "r1" also matches "frr1").
export function flowNode(canvas: Locator, id: string): Locator {
  return canvas.locator(`.react-flow__node[data-id="${id}"]`)
}

export function flowNodes(canvas: Locator): Locator {
  return canvas.locator('.react-flow__node')
}

export function flowEdges(canvas: Locator): Locator {
  return canvas.locator('.react-flow__edge')
}

// Move a node by dragging its body — newly added nodes spawn stacked at the
// same spot, so specs spread them before connecting.
export async function dragNodeBy(page: Page, node: Locator, dx: number, dy: number): Promise<void> {
  // hover() waits for actionability — without it the drag can race the closing
  // palette menu's portal, which still swallows pointer events.
  await node.hover()
  const box = await node.boundingBox()
  if (box === null) throw new Error('dragNodeBy: node not visible')
  const startX = box.x + box.width / 2
  const startY = box.y + box.height / 2
  await page.mouse.move(startX, startY)
  await page.mouse.down()
  // A small first move crosses the drag threshold before the real travel.
  await page.mouse.move(startX + 5, startY + 5)
  await page.mouse.move(startX + dx, startY + dy, { steps: 10 })
  await page.mouse.up()
}

// Drag-to-connect. Each node carries THREE handles: two invisible
// pointer-events-none center handles and the visible right-edge grip
// (data-handleid="drag") — .react-flow__handle alone resolves to a center one
// and the press falls through into a node drag. Press the grip, drop on the
// target's CENTER (the invisible center target catches via connectionRadius).
export async function connectNodes(page: Page, source: Locator, target: Locator): Promise<void> {
  await source.hover()
  const from = await source
    .locator('.react-flow__handle[data-handleid="drag"]')
    .boundingBox()
  const to = await target.boundingBox()
  if (from === null || to === null) throw new Error('connectNodes: grip or target not visible')
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  await page.mouse.move(from.x + 30, from.y + 30)
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 12 })
  await page.mouse.up()
}
