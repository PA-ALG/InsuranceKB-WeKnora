import type { DisplayGraph, GraphMode } from './graphDisplay'
import { seedLayout, type PositionedNode } from './graphLayout'

export function explorationLayout(graph: DisplayGraph, mode: GraphMode, centerId: string): PositionedNode[] {
  const nodes = seedLayout(graph)
  if (mode === 'overview') {
    let top = 0
    for (const group of nodes.filter(node => node.kind === 'group')) {
      const products = nodes.filter(node => node.kind === 'product' && node.group === group.group)
      const rows = Math.ceil(products.length / 3)
      group.x = -360; group.y = top + (rows - 1) * 48
      products.forEach((node, index) => { node.x = -100 + (index % 3) * 280; node.y = top + Math.floor(index / 3) * 96 })
      top += rows * 96 + 32
    }
  } else if (mode === 'neighbors') {
    const neighbors = nodes.filter(node => node.id !== centerId)
    const half = Math.ceil(neighbors.length / 2)
    const radiusY = Math.max(180, half * 22)
    neighbors.forEach((node, index) => {
      const right = index < half, count = right ? half : neighbors.length - half
      // Equal vertical spacing keeps outside labels apart even near the ring's poles.
      const unitY = ((right ? index : index - half) + 0.5) / count * 2 - 1
      node.y = unitY * radiusY
      node.x = (right ? 1 : -1) * 240 * Math.sqrt(1 - unitY * unitY)
    })
    const center = nodes.find(node => node.id === centerId)
    if (center) { center.x = 0; center.y = 0 }
  }
  return nodes
}
