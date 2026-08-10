import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  assertSchemaReadSurface,
  parseSchemaFieldPage,
  parseSchemaPack,
  parseSchemaWikiScope,
} from './schemaWikiContract.ts'

const H = (character: string) => character.repeat(64)
const vector = JSON.parse(readFileSync(new URL(
  '../../../../../internal/application/service/testdata/schema_wiki_contract_vector.json',
  import.meta.url,
), 'utf8')) as {
  schema_pack: Record<string, unknown>
  citations: Array<Record<string, unknown>>
}

function presentField() {
  return {
    contract: 'schema-field-page.v1',
    field_id: 'field-a',
    state: 'present',
    value_snapshot: '示例产品',
    citations: [structuredClone(vector.citations[0])],
    evidence_receipt_sha256s: [H('e')],
    review_item_reason: null,
    field_page_sha256: H('f'),
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

test('generic Wiki source_refs cannot be parsed as a formal Schema field page', () => {
  assert.throws(() => parseSchemaFieldPage({
    ...presentField(),
    source_refs: ['knowledge-terms|terms.pdf'],
  }, { fieldId: 'field-a', fieldPageSha256: H('f') }), {
    message: 'SCHEMA_FIELD_PAGE_INVALID',
  })
})

test('the unchanged A1 SchemaPack is configurable and remains an exact ordered partition', () => {
  const exact = parseSchemaPack(structuredClone(vector.schema_pack))
  assert.deepEqual(exact.ordered_field_ids, ['field-a', 'field-b', 'field-c'])
  assert.deepEqual(exact.sections.map(section => section.section_id), ['section-a', 'section-b'])

  assert.throws(() => parseSchemaPack({
    ...structuredClone(vector.schema_pack),
    sections: [
      { display_name: 'Section A', section_id: 'section-a', ordered_field_ids: ['field-a', 'field-b'] },
      { display_name: 'Section B', section_id: 'section-b', ordered_field_ids: ['field-b', 'field-c'] },
    ],
  }), { message: 'SCHEMA_PACK_TOPOLOGY_INVALID' })
  assert.throws(() => parseSchemaPack({
    ...structuredClone(vector.schema_pack),
    ordered_field_ids: ['field-a\u0000foreign', 'field-b', 'field-c'],
    sections: [
      { display_name: 'Section A', section_id: 'section-a', ordered_field_ids: ['field-a\u0000foreign', 'field-b'] },
      { display_name: 'Section B', section_id: 'section-b', ordered_field_ids: ['field-c'] },
    ],
  }), { message: 'SCHEMA_PACK_TOPOLOGY_INVALID' })
})

test('unknown is an evidence-free abstention and never a hidden answer', () => {
  const unknown = {
    ...presentField(),
    state: 'unknown',
    value_snapshot: null,
    citations: [],
    evidence_receipt_sha256s: [],
    review_item_reason: 'FIELD_UNKNOWN',
  }

  assert.equal(parseSchemaFieldPage(unknown, {
    fieldId: 'field-a',
    fieldPageSha256: H('f'),
  }).state, 'unknown')
  assert.throws(() => parseSchemaFieldPage({ ...unknown, value_snapshot: '猜测值' }, {
    fieldId: 'field-a', fieldPageSha256: H('f'),
  }), { message: 'UNKNOWN_FIELD_HAS_AUTHORITY' })
  assert.throws(() => parseSchemaFieldPage({
    ...unknown,
    citations: [structuredClone(vector.citations[0])],
    evidence_receipt_sha256s: [H('e')],
  }, { fieldId: 'field-a', fieldPageSha256: H('f') }), {
    message: 'UNKNOWN_FIELD_HAS_AUTHORITY',
  })
})

test('absent_explicitly requires a value, citation, and 057 receipt identity', () => {
  assert.throws(() => parseSchemaFieldPage({
    ...presentField(),
    state: 'absent_explicitly',
    value_snapshot: null,
    citations: [],
    evidence_receipt_sha256s: [],
  }, { fieldId: 'field-a', fieldPageSha256: H('f') }), {
    message: 'EXPLICIT_ABSENCE_EVIDENCE_REQUIRED',
  })
})

test('field and field-page pins are checked before render', () => {
  assert.throws(() => parseSchemaFieldPage(presentField(), {
    fieldId: 'field-b', fieldPageSha256: H('f'),
  }), { message: 'SCHEMA_FIELD_PAGE_PIN_MISMATCH' })
  assert.throws(() => parseSchemaFieldPage(presentField(), {
    fieldId: 'field-a', fieldPageSha256: H('9'),
  }), { message: 'SCHEMA_FIELD_PAGE_PIN_MISMATCH' })
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
