import type { Release, SpotSample, SpotVerdict } from '../enterpriseApi'

export function spotRelease(id = 'rel-old', epoch = 1, value: string | string[] = '已发布的字段内容'): Release {
  const make = (kind: string, logical_slug: string, payload: Record<string, unknown>) => ({
    kind, logical_slug, payload, member_digest: 'd'.repeat(64), access_scope: 'space',
  })
  return { id, epoch, members: [
    make('presentation_profile', 'profile/example', { classification_labels: ['example'], sections: [{
      section_key: 'terms', display_name: '保障内容', fields: [{ field_key: 'example_term', short_title: '保障责任' }],
    }] }),
    make('entity', 'entity/item', { entity_id: 'item', names: ['示例保障计划'], classification_labels: ['example'] }),
    make('claim', 'item/term', { subject_ref: 'item', predicate: 'example_term', state: 'present', value,
      origin: 'SOURCE_SUPPORTED', evidence: [{ quote: '对应的原文内容' }] }),
  ] }
}
export function spotSample(id = 'sample-1', releaseId = 'rel-old', extra: Partial<SpotSample> = {}): SpotSample {
  return { id, space_id: 'demo', release_id: releaseId, logical_slug: 'item/term', member_digest: 'd'.repeat(64),
    stratum: 'example/rest', created_by: 'service', created_at: '2026-10-18T12:00:00Z', ...extra }
}
export function spotVerdict(sampleId = 'sample-1'): SpotVerdict {
  return { id: 'verdict-1', sample_id: sampleId, outcome: 'incomplete', note: '请补充适用条件',
    reviewer: 'reviewer:demo', decided_at: '2026-10-18T12:30:00Z' }
}
