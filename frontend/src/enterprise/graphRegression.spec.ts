import { describe, expect, it } from 'vitest'
import { relationGraph } from './graphView'
import { claim, member, release } from './__tests__/s3eFixtures'

describe('relation graph boundaries', () => {
  it('counts distinct product/concept pairs across applicability variants', () => {
    const data = release()
    const expected = relationGraph(data)
    const variant = claim('M1', 'cooling_off_period', 'absent_explicitly', null)
    variant.logical_slug += '/another-region'
    variant.payload.applicability = { region: 'another-region' }
    data.members.push(variant)
    expect(relationGraph(data)).toEqual(expected)
  })

  it('uses the published product domain and excludes other domains and orphan claims', () => {
    const data = structuredClone(release())
    const navigation = data.members.find(item => item.kind === 'navigation')!
    ;(navigation.payload.domains as { entity_types: string[] }[])[0]!.entity_types.push('new_product_type')
    data.members.push(
      member('entity', 'entity/new', { entity_id: 'new', entity_type: 'new_product_type', names: ['New product'] }),
      member('entity', 'entity/service', { entity_id: 'service', entity_type: 'service_benefit', names: ['Service'] }),
      claim('new', 'cooling_off_period', 'present', 'text'),
      claim('service', 'cooling_off_period', 'present', 'text'),
      claim('orphan', 'cooling_off_period', 'present', 'text'),
    )
    const graph = relationGraph(data)
    expect(graph.nodes.some(node => node.id === 'entity:new')).toBe(true)
    expect(graph.nodes.some(node => ['entity:service', 'entity:orphan'].includes(node.id))).toBe(false)
    expect(graph.edges.every(edge => graph.nodes.some(node => node.id === edge.source))).toBe(true)
  })

  it('prefers the concept title and does not mutate its release', () => {
    const data = structuredClone(release())
    data.members.find(item => item.kind === 'concept')!.payload.title = 'Published concept title'
    const before = JSON.stringify(data)
    expect(relationGraph(data).nodes.find(node => node.id === 'concept:cooling_off_period')?.title).toBe('Published concept title')
    expect(JSON.stringify(data)).toBe(before)
  })

  it('keeps non-products out when navigation is absent', () => {
    const data = release({ navigation: false })
    data.members.push(member('entity', 'entity/service', { entity_id: 'service', entity_type: 'service_benefit' }))
    expect(relationGraph(data).nodes.some(node => node.id === 'entity:service')).toBe(false)
  })
})
