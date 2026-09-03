import assert from 'node:assert/strict'
import test from 'node:test'

import { parseEntityPageGraphRead830G1 } from './entityPageGraph830G1Contract.ts'

const SOURCE_RELEASE_ID = 'release-815-source'
const SUCCESSOR_RELEASE_ID = 'release-g1-successor'
const target = { entityId: 'entity-1', pageKind: 'field' as const, stableKey: 'field-1' }

function fieldRead(mode: 'current' | 'pinned' | 'preparation') {
  const servingReleaseID = mode === 'preparation' ? SOURCE_RELEASE_ID : SUCCESSOR_RELEASE_ID
  const data: Record<string, unknown> = {
    contract: 'entity-page-read.830.g1.v1',
    read_mode: mode,
    release_id: servingReleaseID,
    activation_epoch: mode === 'preparation' ? 1 : 2,
    manifest_sha256: 'a'.repeat(64),
    entity_id: target.entityId,
    entity_version_id: 'entity-1@v1',
    display_name: '测试产品',
    classification_display_name: '医疗保险',
    profile: {
      contract: 'presentation-profile.v1',
      profile_id: 'profile-1',
      profile_version: '1',
      schema_pack_id: 'pack-1',
      schema_version: '1',
      schema_pack_sha256: 'b'.repeat(64),
      profile_sha256: 'c'.repeat(64),
      sections: [{
        section_key: 'section-1',
        display_name: '分类一',
        fields: [{ field_key: target.stableKey, short_title: '字段一' }],
      }],
    },
    member: {
      contract: 'entity-page-member.830.g1.v1',
      page_id: 'page-1',
      namespace: 'urn:jlx:wiki:space-1:entity:entity-1:field:field-1',
      route: '/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/fields/field-1',
      page_kind: target.pageKind,
      stable_key: target.stableKey,
      short_title: '字段一',
      space_id: 'space-1',
      wiki_kb_id: 'wiki-1',
      entity_id: target.entityId,
      release_id: SOURCE_RELEASE_ID,
      candidate_sha256: 'd'.repeat(64),
      claim_set_sha256: 'e'.repeat(64),
      evidence_authority_sha256: 'f'.repeat(64),
      schema_pack_sha256: 'b'.repeat(64),
      profile_sha256: 'c'.repeat(64),
      payload: {
        contract: 'field-assertion-page.830.g1.v1',
        field_key: target.stableKey,
        reference: {
          field_key: target.stableKey,
          page_id: 'page-1',
          source_release_id: SOURCE_RELEASE_ID,
          source_candidate_sha256: 'd'.repeat(64),
          product_version_id: 'entity-1@v1',
          claim_sha256: '1'.repeat(64),
          evidence_receipt_sha256s: [],
          citation_sha256s: [],
        },
        state: 'unknown',
        value_snapshot: null,
        display_value: null,
        unknown_reason: 'FIELD_UNKNOWN',
        source_typed_reason: 'SOURCE_NOT_AVAILABLE',
        citations: [],
      },
      payload_sha256: '2'.repeat(64),
      member_digest: '3'.repeat(64),
    },
  }
  if (mode === 'preparation') data.preparation_id = 'preparation-g1'
  return { success: true, data }
}

function memberOf(value: ReturnType<typeof fieldRead>): Record<string, unknown> {
  return value.data.member as Record<string, unknown>
}

function referenceOf(value: ReturnType<typeof fieldRead>): Record<string, unknown> {
  return (memberOf(value).payload as Record<string, unknown>).reference as Record<string, unknown>
}

for (const mode of ['current', 'pinned'] as const) {
  test(`accepts ${mode} serving identity without rewriting the frozen source member`, () => {
    const parsed = parseEntityPageGraphRead830G1(fieldRead(mode), target)
    assert.equal(parsed.release_id, SUCCESSOR_RELEASE_ID)
    assert.equal(parsed.member.release_id, SOURCE_RELEASE_ID)
    assert.equal(
      (parsed.member.payload as unknown as { reference: { source_release_id: string } }).reference.source_release_id,
      SOURCE_RELEASE_ID,
    )
  })
}

test('keeps preparation serving, member, and reference identities equal', () => {
  const parsed = parseEntityPageGraphRead830G1(fieldRead('preparation'), target)
  assert.equal(parsed.release_id, SOURCE_RELEASE_ID)
  assert.equal(parsed.member.release_id, SOURCE_RELEASE_ID)
  assert.equal(
    (parsed.member.payload as unknown as { reference: { source_release_id: string } }).reference.source_release_id,
    SOURCE_RELEASE_ID,
  )
})

for (const invalid of [
  {
    name: 'source member rewritten to successor',
    mutate: (value: ReturnType<typeof fieldRead>) => { memberOf(value).release_id = SUCCESSOR_RELEASE_ID },
  },
  {
    name: 'reference differs from source member',
    mutate: (value: ReturnType<typeof fieldRead>) => { referenceOf(value).source_release_id = 'release-foreign' },
  },
  {
    name: 'current serving release equals source release',
    mutate: (value: ReturnType<typeof fieldRead>) => { value.data.release_id = SOURCE_RELEASE_ID },
  },
]) {
  test(`rejects ${invalid.name}`, () => {
    const value = fieldRead('current')
    invalid.mutate(value)
    assert.throws(
      () => parseEntityPageGraphRead830G1(value, target),
      /ENTITY_PAGE_GRAPH_RESPONSE_INVALID/,
    )
  })
}

test('rejects preparation envelope drift from its source member', () => {
  const value = fieldRead('preparation')
  value.data.release_id = SUCCESSOR_RELEASE_ID
  assert.throws(
    () => parseEntityPageGraphRead830G1(value, target),
    /ENTITY_PAGE_GRAPH_RESPONSE_INVALID/,
  )
})
