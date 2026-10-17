// S3d-3a acceptance (protected, written by Claude): a release becomes entity summaries and entity
// pages by the S3d-2 reader rules (Spec docs/design/slices/S3d-3a-企业知识页面.md §3.2).
import { describe, expect, it } from 'vitest'
import type { Release, ReleaseMember } from './enterpriseApi'
import { entitySummaries, entityView } from './releaseView'

function member(kind: string, slug: string, payload: Record<string, unknown>): ReleaseMember {
  return { kind, logical_slug: slug, payload, member_digest: 'd'.repeat(64), access_scope: 'space' }
}

function claim(subject: string, predicate: string, state: string, value: unknown, origin: string, evidence: number) {
  const slug = `${subject}/${predicate}`
  return member('claim', slug, {
    claim_id: slug, logical_key: slug, subject_ref: subject, predicate, state, value, origin,
    evidence: Array.from({ length: evidence }, (_, index) => ({ source_ref: `source:v1:k:1:${'a'.repeat(64)}`, quote: `q${index}` })),
  })
}

const profile = member('presentation_profile', 'presentation/profile_a', {
  profile_id: 'profile_a', profile_version: '1', profile_sha256: 'a'.repeat(64), schema_pack_id: 'pack_a',
  classification_labels: ['class_a'],
  sections: [
    { section_key: 'overview', display_name: '概览', fields: [
      { field_key: 'f_name', short_title: '名称' }, { field_key: 'f_missing', short_title: '没有发布' }] },
    { section_key: 'terms', display_name: '条款', fields: [
      { field_key: 'f_wait', short_title: '等待期' }, { field_key: 'f_grace', short_title: '宽限期' },
      { field_key: 'f_hint', short_title: '提示' }] },
    { section_key: 'empty', display_name: '空分组', fields: [{ field_key: 'f_none', short_title: '无' }] },
  ],
})

const release: Release = {
  id: 'rel-1',
  epoch: 3,
  members: [
    profile,
    member('entity', 'entity/P1', { entity_id: 'P1', entity_type: 'product', names: ['乙产品', '别名'], classification_labels: ['class_a'], owner_module: 'm' }),
    member('entity', 'entity/P2', { entity_id: 'P2', entity_type: 'product', names: ['甲产品'], classification_labels: ['class_b'], owner_module: 'm' }),
    claim('P1', 'f_grace', 'absent_explicitly', null, 'SOURCE_SUPPORTED', 1),
    claim('P1', 'f_wait', 'present', '90日', 'SOURCE_SUPPORTED', 2),
    claim('P1', 'f_name', 'present', ['A', 'B'], 'EXPERT_REVISION', 1),
    claim('P1', 'z_extra', 'unknown', null, 'SOURCE_SUPPORTED', 0),
    claim('P1', 'a_extra', 'present', 3, 'STRUCTURED_IMPORT', 1),
    claim('P1', 'f_hint', 'present', '通用说明', 'MODEL_GENERATED', 0),
    claim('P1', 'f_concept', 'present', '通用解释', 'MODEL_GENERATED', 0),
    claim('P3', 'f_wait', 'present', true, 'SOURCE_SUPPORTED', 1),
    claim('P2', 'f_wait', 'present', '30日', 'SOURCE_SUPPORTED', 1),
  ],
}

describe('entity summaries', () => {
  it('lists entity members in release order, then subjects published without one', () => {
    expect(entitySummaries(release)).toEqual([
      { entityId: 'P1', name: '乙产品', labels: ['class_a'], fieldCount: 7 },
      { entityId: 'P2', name: '甲产品', labels: ['class_b'], fieldCount: 1 },
      { entityId: 'P3', name: 'P3', labels: [], fieldCount: 1 },
    ])
  })

  it('names an entity by its id when it has no names and lists an empty release as empty', () => {
    const bare = { ...release, members: [member('entity', 'entity/X', { entity_id: 'X', names: [] })] }
    expect(entitySummaries(bare)).toEqual([{ entityId: 'X', name: 'X', labels: [], fieldCount: 0 }])
    expect(entitySummaries({ ...release, members: [] })).toEqual([])
  })
})

describe('entity view', () => {
  it('shows only published fields in the profile order and keeps model content apart', () => {
    const view = entityView(release, 'P1')!
    expect(view.name).toBe('乙产品')
    expect(view.labels).toEqual(['class_a'])
    expect(view.sections.map(section => [section.key, section.title, section.fields.map(field => field.slug)])).toEqual([
      ['overview', '概览', ['P1/f_name']],
      ['terms', '条款', ['P1/f_wait', 'P1/f_grace']],
    ])
    expect(view.other.map(field => [field.slug, field.title])).toEqual([
      ['P1/a_extra', 'a_extra'],
      ['P1/z_extra', 'z_extra'],
    ])
    expect(view.generated.map(field => [field.slug, field.title, field.origin])).toEqual([
      ['P1/f_concept', 'f_concept', 'MODEL_GENERATED'],
      ['P1/f_hint', '提示', 'MODEL_GENERATED'],
    ])
  })

  it('formats values by state and counts evidence', () => {
    const view = entityView(release, 'P1')!
    const fields = [...view.sections.flatMap(section => section.fields), ...view.other, ...view.generated]
    const bySlug = Object.fromEntries(fields.map(field => [field.slug, field]))
    expect(bySlug['P1/f_wait']).toEqual({
      slug: 'P1/f_wait', title: '等待期', state: 'present', value: '90日', origin: 'SOURCE_SUPPORTED', evidenceCount: 2,
    })
    expect(bySlug['P1/f_name'].value).toEqual(['A', 'B'])
    expect(bySlug['P1/f_grace']).toMatchObject({ state: 'absent_explicitly', value: null, evidenceCount: 1 })
    expect(bySlug['P1/z_extra']).toMatchObject({ state: 'unknown', value: null, evidenceCount: 0 })
    expect(bySlug['P1/a_extra'].value).toBe('3')
    expect(entityView(release, 'P3')!.other[0].value).toBe('true')
  })

  it('uses only a profile that shares a classification label, and reads old releases without one', () => {
    const other = entityView(release, 'P2')!
    expect(other.sections).toEqual([])
    expect(other.other.map(field => [field.slug, field.title])).toEqual([['P2/f_wait', 'f_wait']])

    const orphan = entityView(release, 'P3')!
    expect(orphan).toMatchObject({ entityId: 'P3', name: 'P3', labels: [], sections: [], generated: [] })
    expect(orphan.other.map(field => field.slug)).toEqual(['P3/f_wait'])
  })

  it('returns nothing for an entity the release does not hold', () => {
    expect(entityView(release, 'missing')).toBeNull()
  })

  it('treats a claim without origin or an evidence list as unlabelled and uncited', () => {
    const odd = member('claim', 'Q/x', { subject_ref: 'Q', predicate: 'x', state: 'present', value: 'v', evidence: 'none' })
    const view = entityView({ ...release, members: [odd] }, 'Q')!
    expect(view.other).toEqual([{ slug: 'Q/x', title: 'x', state: 'present', value: 'v', origin: '', evidenceCount: 0 }])
  })
})
