import type { GraphNode, GraphEdge, RelationGraph } from './graphView'

export interface DisplayNode extends Omit<GraphNode, 'kind'> { kind: GraphNode['kind'] | 'group' }
export interface DisplayGraph { nodes: DisplayNode[]; edges: GraphEdge[] }
export type GraphMode = 'overview' | 'neighbors' | 'all'

// Project one published graph without changing its nodes, degrees or relationships.
export function graphDisplay(graph: RelationGraph, groups: readonly string[], showAll = false, centerId = ''):
  { available: RelationGraph; visible: DisplayGraph; mode: GraphMode } {
  const enabled = new Set(groups)
  const products = graph.nodes.filter(node => node.kind === 'product' && enabled.has(node.group))
  const productIds = new Set(products.map(node => node.id))
  const edges = graph.edges.filter(edge => productIds.has(edge.source))
  const conceptIds = new Set(edges.map(edge => edge.target))
  const available = { nodes: graph.nodes.filter(node => productIds.has(node.id) || conceptIds.has(node.id)), edges }
  if (showAll) return { available, visible: available, mode: 'all' }
  if (available.nodes.some(node => node.id === centerId)) {
    const incident = edges.filter(edge => edge.source === centerId || edge.target === centerId)
    const neighbors = new Set([centerId, ...incident.flatMap(edge => [edge.source, edge.target])])
    return { available, visible: { nodes: available.nodes.filter(node => neighbors.has(node.id)), edges: incident }, mode: 'neighbors' }
  }
  const groupNodes = new Map<string, DisplayNode>()
  for (const product of products) {
    const group = groupNodes.get(product.group) ?? { id: `group:${encodeURIComponent(product.group)}`, kind: 'group',
      title: product.groupTitle, group: product.group, groupTitle: product.groupTitle, degree: 0 }
    group.degree++
    groupNodes.set(product.group, group)
  }
  return { available, mode: 'overview', visible: { nodes: [...groupNodes.values(), ...products],
    edges: products.map(product => ({ source: product.id, target: groupNodes.get(product.group)!.id })) } }
}
