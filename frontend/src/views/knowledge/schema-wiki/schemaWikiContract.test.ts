import assert from 'node:assert/strict'
import test from 'node:test'

import {
  assertSchemaReadSurface,
  parseSchemaFieldMember,
  parseSchemaPack,
  parseSchemaWikiScope,
} from './schemaWikiContract.ts'

const H = (character: string) => character.repeat(64)

function citation(pageNumber = 12) {
  return {
    version: 'citation-target.v1',
    citation_id: `citation-page-${pageNumber}`,
    citation_sha256: H('c'),
    logical_member_ref: 'fields/product_name',
    knowledge_id: 'knowledge-terms',
    source_revision_id: 'knowledge-terms:attempt-2',
    parse_attempt: 2,
    document_sha256: H('d'),
    manifest_sha256: H('e'),
    chunk_id: 'chunk-12',
    page_number: pageNumber,
    locator_kind: 'block',
    locator_id: 'block-12',
    bbox: {
      x0: 100,
      y0: 200,
      x1: 400,
      y1: 300,
      coordinate_space: 'normalized_0_1000',
    },
    quote_sha256: H('f'),
    content_sha256: H('a'),
  }
}

function presentField() {
  return {
    version: 'schema-field-member.v1',
    release_id: 'release-r1',
    member_digest: H('b'),
    logical_slug: 'fields/product_name',
    section_id: 'product-overview',
    field_id: 'product_name',
    state: 'present',
    value: '示例产品',
    citations: [citation()],
    citation_bindings: [{
      citation_sha256: H('c'),
      member_digest: H('b'),
    }],
    review_items: [],
  }
}

test('scope bootstrap is closed and callers cannot cross-combine Space or KB identities', () => {
  const scope = parseSchemaWikiScope({
    version: 'schema-wiki-scope.v1',
    space_id: 'space-1',
    raw_kb_id: 'raw-1',
    wiki_kb_id: 'wiki-1',
    scope_sha256: H('1'),
  })

  assert.equal(scope.space_id, 'space-1')
  assert.equal(Object.isFrozen(scope), true)
  assert.throws(() => {
    scope.raw_kb_id = 'raw-foreign'
  }, TypeError)
})

test('generic Wiki source_refs cannot be parsed as a formal Schema member', () => {
  assert.throws(() => parseSchemaFieldMember({
    ...presentField(),
    source_refs: ['knowledge-terms|terms.pdf'],
  }, {
    releaseId: 'release-r1',
    memberDigest: H('b'),
  }), {
    message: 'SCHEMA_FIELD_MEMBER_INVALID',
  })
})

test('SchemaPack topology is configurable but remains an exact section-to-field bijection', () => {
  const configurablePack = {
    version: 'schema-pack.v1',
    domain_id: 'future-configured-domain',
    schema_pack_id: 'future-pack.v1',
    schema_pack_sha256: H('2'),
    fields: [
      { field_id: 'alpha', ordinal: 0 },
      { field_id: 'beta', ordinal: 1 },
    ],
    sections: [
      { section_id: 'first', ordinal: 0, field_ids: ['alpha'] },
      { section_id: 'second', ordinal: 1, field_ids: ['beta'] },
    ],
  }

  assert.deepEqual(
    parseSchemaPack(configurablePack).sections.map(section => section.section_id),
    ['first', 'second'],
  )
  assert.throws(() => parseSchemaPack({
    ...configurablePack,
    sections: [
      { section_id: 'first', ordinal: 0, field_ids: ['alpha', 'beta'] },
      { section_id: 'second', ordinal: 1, field_ids: ['beta'] },
    ],
  }), { message: 'SCHEMA_PACK_TOPOLOGY_INVALID' })
})

test('unknown is an evidence-free abstention and never a hidden answer', () => {
  const unknown = {
    ...presentField(),
    state: 'unknown',
    value: null,
    citations: [],
    citation_bindings: [],
    review_items: [{ reason_code: 'FIELD_VALUE_UNKNOWN' }],
  }

  assert.equal(parseSchemaFieldMember(unknown, {
    releaseId: 'release-r1',
    memberDigest: H('b'),
  }).state, 'unknown')
  assert.throws(() => parseSchemaFieldMember({ ...unknown, value: '猜测值' }, {
    releaseId: 'release-r1',
    memberDigest: H('b'),
  }), { message: 'UNKNOWN_FIELD_HAS_AUTHORITY' })
  assert.throws(() => parseSchemaFieldMember({
    ...unknown,
    citations: [citation()],
    citation_bindings: [{ citation_sha256: H('c'), member_digest: H('b') }],
  }, {
    releaseId: 'release-r1',
    memberDigest: H('b'),
  }), { message: 'UNKNOWN_FIELD_HAS_AUTHORITY' })
})

test('absent_explicitly requires a value and replayable explicit Evidence', () => {
  assert.throws(() => parseSchemaFieldMember({
    ...presentField(),
    state: 'absent_explicitly',
    value: null,
    citations: [],
    citation_bindings: [],
  }, {
    releaseId: 'release-r1',
    memberDigest: H('b'),
  }), { message: 'EXPLICIT_ABSENCE_EVIDENCE_REQUIRED' })
})

test('release and member pins are checked before a field can render', () => {
  assert.throws(() => parseSchemaFieldMember(presentField(), {
    releaseId: 'release-r2',
    memberDigest: H('b'),
  }), { message: 'SCHEMA_FIELD_RELEASE_PIN_MISMATCH' })
  assert.throws(() => parseSchemaFieldMember(presentField(), {
    releaseId: 'release-r1',
    memberDigest: H('9'),
  }), { message: 'SCHEMA_FIELD_MEMBER_PIN_MISMATCH' })
})

test('reviewed preparation is not accepted by current or search surfaces', () => {
  const preparation = {
    surface: 'preparation',
    preparation_id: 'preparation-1',
    status: 'reviewed',
  }
  assert.throws(() => assertSchemaReadSurface(preparation, 'current'), {
    message: 'SCHEMA_DRAFT_NOT_ACTIVE',
  })
  assert.throws(() => assertSchemaReadSurface(preparation, 'search'), {
    message: 'SCHEMA_DRAFT_NOT_SEARCHABLE',
  })
})
