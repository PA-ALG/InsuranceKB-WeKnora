import type { Release, ReleaseMember } from '../enterpriseApi'

export function homeMember(kind: string, slug: string, payload: Record<string, unknown>): ReleaseMember {
  return { kind, logical_slug: slug, payload, member_digest: 'd'.repeat(64), access_scope: 'space' }
}

export function homeClaim(subject: string, predicate: string, value: unknown, state = 'present', suffix = '') {
  return homeMember('claim', `${subject}/${predicate}${suffix}`, {
    subject_ref: subject, predicate, value, state, origin: 'SOURCE_SUPPORTED', evidence: [],
  })
}

export function homeRelease(): Release {
  const fields = Array.from({ length: 12 }, (_, index) => ({ field_key: `field_${index}`, short_title: `字段 ${index}` }))
  return {
    id: 'home-release', epoch: 12,
    members: [
      homeMember('navigation', 'nav', {
        display_name: '示例知识库', overview_fields: ['field_1', 'field_0'],
        domains: [{ domain_key: 'products', display_name: '产品', entity_types: ['demo_product'], groups: [
          { group_key: 'alpha', display_name: '第一组', classification_labels: ['a'] },
          { group_key: 'empty', display_name: '空组', classification_labels: ['empty'] },
          { group_key: 'beta', display_name: '第二组', classification_labels: ['b'] },
        ] }],
      }),
      ...['a', 'b'].map(label => homeMember('presentation_profile', `profile/${label}`, {
        classification_labels: [label], sections: [{ section_key: 'terms', display_name: '条款', fields }],
      })),
      ...['A', 'B', 'C'].map((entityId, index) => homeMember('entity', entityId, {
        entity_id: entityId, entity_type: 'demo_product', names: [`产品 ${entityId}`], classification_labels: [index < 2 ? 'a' : 'b'],
      })),
      ...fields.flatMap(field => ['A', 'B'].map(subject => homeClaim(subject, field.field_key, '保障为20日，详见条款。'))),
      homeClaim('C', 'field_2', null, 'absent_explicitly'),
      homeClaim('C', 'field_0', null, 'unknown'),
    ],
  }
}
