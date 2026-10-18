import type { RelationGraph } from './graphView'

// A display projection only: published nodes, degrees and the full relationGraph stay intact.
export function graphDisplay(graph: RelationGraph, groups: readonly string[], showAll = false, locatedId = '') {
  const enabled = new Set(groups)
  const products = new Set(graph.nodes.filter(node => node.kind === 'product' && enabled.has(node.group)).map(node => node.id))
  const edges = graph.edges.filter(edge => products.has(edge.source))
  const subjects = new Map<string, Set<string>>()
  for (const edge of edges) {
    if (!subjects.has(edge.target)) subjects.set(edge.target, new Set())
    subjects.get(edge.target)!.add(edge.source)
  }
  // No visible products means no eligible concepts, not a vacuously universal relation.
  const common = new Set([...subjects].filter(([, ids]) => products.size > 0 && ids.size === products.size).map(([id]) => id))
  const shown = new Set([...subjects.keys()].filter(id => showAll || !common.has(id) || id === locatedId))
  const available = { nodes: graph.nodes.filter(node => products.has(node.id) || subjects.has(node.id)), edges }
  const visible = { nodes: available.nodes.filter(node => products.has(node.id) || shown.has(node.id)),
    edges: edges.filter(edge => shown.has(edge.target)) }
  const revealedConceptCount = !showAll && common.has(locatedId) ? 1 : 0
  return { available, visible, hiddenConceptCount: showAll ? 0 : common.size - revealedConceptCount, revealedConceptCount }
}
