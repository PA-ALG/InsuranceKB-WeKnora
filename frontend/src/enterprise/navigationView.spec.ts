// S3e-2 acceptance (protected, written by Claude): the navigation tree comes from the release's
// navigation member — domain by entity type, group by classification label, empty groups and
// domains hidden, the rest under "other" — and falls back to one flat list without it
// (Spec docs/design/slices/S3e-企业知识导航与概念页.md §2.1).
import { describe, expect, it } from 'vitest'
import { navigationTree } from './navigationView'
import { member, release } from './s3eFixtures'

const ids = (entries: { entityId: string }[]) => entries.map(entry => entry.entityId)

describe('navigationTree', () => {
  it('groups entries by domain and pack, hiding what holds nothing', () => {
    const tree = navigationTree(release())
    expect(tree.map(domain => [domain.key, domain.title])).toEqual([['product', '产品库']])
    const [product] = tree
    expect(product.groups.map(group => [group.key, group.title, ids(group.entries)])).toEqual([
      ['pack_medical', '医疗险', ['M1', 'M2']],
      ['pack_critical', '重疾险', ['C1']],
      ['__other__', '', ['X1']],
    ])
    expect(product.groups[0].entries[0].name).toBe('甲医疗')
  })

  it('puts an entity of no known domain into a trailing other domain', () => {
    const base = release()
    const stray = member('entity', 'entity/S1', { entity_id: 'S1', entity_type: 'mystery', names: ['戊'], classification_labels: [] })
    const tree = navigationTree({ ...base, members: [...base.members, stray] })
    expect(tree.map(domain => domain.key)).toEqual(['product', '__other__'])
    expect(tree[1].groups.map(group => [group.key, ids(group.entries)])).toEqual([['__other__', ['S1']]])
  })

  it('shows a service domain once it has entries', () => {
    const base = release()
    const service = member('entity', 'entity/F1', {
      entity_id: 'F1', entity_type: 'service_benefit', names: ['臻享家医'], classification_labels: ['family_doctor'],
    })
    const tree = navigationTree({ ...base, members: [...base.members, service] })
    expect(tree.map(domain => domain.title)).toEqual(['产品库', '服务权益'])
    expect(tree[1].groups.map(group => [group.title, ids(group.entries)])).toEqual([['家庭医生', ['F1']]])
  })

  it('falls back to one flat list when the release has no navigation member', () => {
    const tree = navigationTree(release({ navigation: false }))
    expect(tree).toHaveLength(1)
    expect(tree[0].key).toBe('')
    expect(tree[0].groups).toHaveLength(1)
    expect(ids(tree[0].groups[0].entries)).toEqual(['M1', 'M2', 'C1', 'X1'])
  })
})
