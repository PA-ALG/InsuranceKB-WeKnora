// Force equations adapted from WeKnora's views/knowledge/wiki/WikiBrowser.vue (MIT).
// This layout consumes only enterprise graph data; it has no native Wiki reads or state.
import type { DisplayNode, DisplayGraph } from './graphDisplay'

export interface PositionedNode extends DisplayNode { x: number; y: number; vx: number; vy: number; pinned: boolean }
export const nodeRadius = (node: DisplayNode) => 9 + Math.min(10, Math.sqrt(node.degree) * 3)

export function seedLayout(graph: DisplayGraph): PositionedNode[] {
  return graph.nodes.map((node, index) => {
    const angle = index * Math.PI * (3 - Math.sqrt(5))
    const distance = 75 * Math.sqrt(index + 1)
    return { ...node, x: Math.cos(angle) * distance, y: Math.sin(angle) * distance, vx: 0, vy: 0, pinned: false }
  })
}

export function stepLayout(nodes: PositionedNode[], graph: DisplayGraph, alpha: number): void {
  const sorted = [...nodes].sort((a, b) => a.x - b.x)
  // Bounded repulsion, as in the upstream canvas. Sorting skips distant pairs.
  for (let i = 0; i < sorted.length; i++) {
    const a = sorted[i]!
    for (let j = i + 1; j < sorted.length; j++) {
      const b = sorted[j]!, dx = b.x - a.x, dy = b.y - a.y
      if (dx > 300) break
      const squared = dx * dx + dy * dy
      if (squared > 90000) continue
      const distance = Math.sqrt(squared) || 1
      const force = 14000 * alpha / Math.max(squared, 100)
      const fx = (dx || 0.1) / distance * force, fy = dy / distance * force
      if (!a.pinned) { a.vx -= fx; a.vy -= fy }
      if (!b.pinned) { b.vx += fx; b.vy += fy }
    }
  }
  const byId = new Map(nodes.map(node => [node.id, node]))
  for (const edge of graph.edges) {
    const a = byId.get(edge.source), b = byId.get(edge.target)
    if (!a || !b) continue
    const dx = b.x - a.x, dy = b.y - a.y, distance = Math.hypot(dx, dy) || 1
    const force = (distance - 160) * 0.025 * alpha
    if (!a.pinned) { a.vx += dx / distance * force; a.vy += dy / distance * force }
    if (!b.pinned) { b.vx -= dx / distance * force; b.vy -= dy / distance * force }
  }
  for (const node of nodes) {
    if (node.pinned) continue
    node.vx = (node.vx - node.x * 0.003 * alpha) * 0.6
    node.vy = (node.vy - node.y * 0.003 * alpha) * 0.6
    const speed = Math.hypot(node.vx, node.vy)
    const cap = speed > 20 ? 20 / speed : 1
    node.x += node.vx * cap
    node.y += node.vy * cap
  }
}
