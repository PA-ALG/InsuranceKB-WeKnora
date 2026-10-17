// Regression (PR #188 review R1): a predicate is not a claim's identity. Claims that share a
// predicate but differ in slug (e.g. applicability) must all be shown, with or without a profile.
import { describe, expect, it } from 'vitest'
import type { Release, ReleaseMember } from './enterpriseApi'
import { entitySummaries, entityView } from './releaseView'

function member(kind: string, slug: string, payload: Record<string, unknown>): ReleaseMember {
  return { kind, logical_slug: slug, payload, member_digest: 'd'.repeat(64), access_scope: 'space' }
}

function claim(slug: string, predicate: string, value: string, origin = 'SOURCE_SUPPORTED') {
  return member('claim', slug, {
    subject_ref: 'P1', predicate, state: 'present', value, origin, evidence: [{ quote: value }],
  })
}

const claims = [
  claim('P1/term_a/web', 'term_a', '30日'),
  claim('P1/term_a/agency', 'term_a', '90日'),
  claim('P1/term_b/web', 'term_b', '1'),
  claim('P1/term_b/agency', 'term_b', '2'),
  claim('P1/note/b', 'note', 'x', 'MODEL_GENERATED'),
  claim('P1/note/a', 'note', 'y', 'MODEL_GENERATED'),
]
const entity = member('entity', 'entity/P1', { entity_id: 'P1', names: ['产品'], classification_labels: ['class_a'] })
const profile = member('presentation_profile', 'presentation/p', {
  profile_id: 'p', classification_labels: ['class_a'],
  sections: [{ section_key: 'terms', display_name: '条款', fields: [{ field_key: 'term_a', short_title: '期限' }] }],
})

function release(members: ReleaseMember[]): Release {
  return { id: 'rel-1', epoch: 1, members }
}

describe('claims sharing a predicate', () => {
  it('keeps every claim of a profile field, ordered by slug, under the field title', () => {
    const view = entityView(release([entity, profile, ...claims]), 'P1')!
    expect(view.sections[0].fields.map(field => [field.slug, field.title, field.value])).toEqual([
      ['P1/term_a/agency', '期限', '90日'],
      ['P1/term_a/web', '期限', '30日'],
    ])
    expect(view.other.map(field => field.slug)).toEqual(['P1/term_b/agency', 'P1/term_b/web'])
    expect(view.generated.map(field => field.slug)).toEqual(['P1/note/a', 'P1/note/b'])
  })

  it('keeps them all without a profile, and the page shows as many fields as the summary counts', () => {
    const plain = release([member('entity', 'entity/P1', { entity_id: 'P1', names: ['产品'] }), ...claims])
    const view = entityView(plain, 'P1')!
    const shown = [...view.sections.flatMap(section => section.fields), ...view.other, ...view.generated]
    expect(view.other.map(field => field.slug)).toEqual([
      'P1/term_a/agency', 'P1/term_a/web', 'P1/term_b/agency', 'P1/term_b/web',
    ])
    expect(shown).toHaveLength(entitySummaries(plain)[0].fieldCount)
  })
})
