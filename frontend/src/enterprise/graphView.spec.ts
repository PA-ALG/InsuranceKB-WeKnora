// S3g acceptance (protected, written by Claude): the relation graph is built from the release alone
// (Spec docs/design/slices/S3g-知识图谱复用.md §2.1).
import { describe, expect, it } from 'vitest'
import { conceptKeys } from './conceptView'
import { relationGraph } from './graphView'
import { claim, release as s3eRelease } from './__tests__/s3eFixtures'

describe('relation graph', () => {
  it('links each product to the concepts it states, grouped by navigation', () => {
    const release = s3eRelease()
    const graph = relationGraph(release)
    const products = graph.nodes.filter(node => node.kind === 'product')
    const concepts = graph.nodes.filter(node => node.kind === 'concept')
    expect(concepts.map(node => node.id)).toEqual(conceptKeys(release).map(key => `concept:${key}`))
    expect(concepts.find(node => node.id === 'concept:cooling_off_period')?.title).toBe('犹豫期')
    expect(products.every(node => node.id.startsWith('entity:'))).toBe(true)
    expect(products.find(node => node.id === 'entity:M1')).toMatchObject({ group: 'pack_medical', groupTitle: '医疗险' })
    expect(products.find(node => node.id === 'entity:X1')?.group).toBe('__other__') // as navigationTree does
    for (const edge of graph.edges) {
      expect(edge.source.startsWith('entity:') && edge.target.startsWith('concept:')).toBe(true)
    }
    const degrees = new Map(graph.nodes.map(node => [node.id, node.degree]))
    for (const node of graph.nodes) {
      expect(degrees.get(node.id)).toBe(graph.edges.filter(edge => edge.source === node.id || edge.target === node.id).length)
    }
    expect(relationGraph(release)).toEqual(graph) // the same release gives the same graph
  })

  it('links present and explicitly absent values, never unknown ones', () => {
    const release = s3eRelease()
    release.members.push(
      claim('M1', 'zz_probe', 'present', 'x'),
      claim('M2', 'zz_probe', 'absent_explicitly', null),
      claim('C1', 'zz_probe', 'unknown', null, 0),
    )
    const edges = relationGraph(release).edges.filter(edge => edge.target === 'concept:zz_probe')
    expect(edges.map(edge => edge.source).sort()).toEqual(['entity:M1', 'entity:M2'])
  })

  it('works without a navigation or concept members', () => {
    const graph = relationGraph(s3eRelease({ navigation: false, concept: false }))
    expect(graph.nodes.filter(node => node.kind === 'product').every(node => node.group === '')).toBe(true)
    expect(graph.nodes.find(node => node.id === 'concept:cooling_off_period')?.title).toBe('犹豫期') // the profile title
  })
})
