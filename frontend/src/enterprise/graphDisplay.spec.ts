import { describe, expect, it } from 'vitest'
import { graphDisplay } from './graphDisplay'
import type { GraphNode, RelationGraph } from './graphView'

const node = (id: string, kind: GraphNode['kind'], group = ''): GraphNode => ({ id, kind, group, groupTitle: group, title: id, degree: 0 })
const graph: RelationGraph = {
  nodes: [node('a', 'product', 'one'), node('b', 'product', 'one'), node('c', 'product', 'two'),
    node('shared', 'concept'), node('partial', 'concept'), node('isolated', 'concept')],
  edges: [{ source: 'a', target: 'shared' }, { source: 'b', target: 'shared' }, { source: 'c', target: 'shared' },
    { source: 'a', target: 'partial' }, { source: 'b', target: 'partial' }],
}

describe('graph display filtering', () => {
  it('hides universally connected concepts without changing the full graph', () => {
    const before = JSON.stringify(graph)
    const display = graphDisplay(graph, ['one', 'two'])
    expect(display.visible.nodes.map(node => node.id)).toEqual(['a', 'b', 'c', 'partial'])
    expect(display.visible.edges).toHaveLength(2)
    expect(display.hiddenConceptCount).toBe(1)
    expect(display.available.nodes.map(node => node.id)).toContain('shared')
    expect(JSON.stringify(graph)).toBe(before)
  })

  it('restores all connected concepts when requested, and recomputes after group filtering', () => {
    expect(graphDisplay(graph, ['one', 'two'], true).visible.edges).toHaveLength(5)
    const narrowed = graphDisplay(graph, ['one'])
    expect(narrowed.visible.nodes.map(node => node.id)).toEqual(['a', 'b'])
    expect(narrowed.hiddenConceptCount).toBe(2)
    const all = graphDisplay(graph, ['one'], true)
    expect(all.visible.edges).toHaveLength(4)
    expect(all.hiddenConceptCount).toBe(0)
  })

  it('reveals only the located concept and its currently eligible edges', () => {
    const located = graphDisplay(graph, ['one'], false, 'shared')
    expect(located.visible.nodes.map(node => node.id)).toEqual(['a', 'b', 'shared'])
    expect(located.visible.edges).toHaveLength(2)
    expect(located.hiddenConceptCount).toBe(1)
    expect(located.revealedConceptCount).toBe(1)
    expect(graphDisplay(graph, ['one'], false, 'isolated').revealedConceptCount).toBe(0)
  })

  it('handles zero and one visible product without inventing hidden nodes', () => {
    const empty = graphDisplay(graph, [], false, 'shared')
    expect(empty.visible).toEqual({ nodes: [], edges: [] })
    expect(empty.hiddenConceptCount).toBe(0)
    expect(empty.revealedConceptCount).toBe(0)
    const single = graphDisplay(graph, ['two'])
    expect(single.visible.nodes.map(node => node.id)).toEqual(['c'])
    expect(single.hiddenConceptCount).toBe(1)
    expect(graphDisplay(graph, ['two'], true).visible.edges).toHaveLength(1)
  })
})
