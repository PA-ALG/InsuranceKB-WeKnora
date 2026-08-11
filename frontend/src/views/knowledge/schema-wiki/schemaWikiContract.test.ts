import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  assertSchemaReadSurface,
  parseSchemaFieldPage,
  parseSchemaPack,
  parseSchemaWikiCurrentEntityVersion,
  parseSchemaWikiScope,
} from './schemaWikiContract.ts'

const H = (character: string) => character.repeat(64)
const vector = JSON.parse(readFileSync(new URL(
  '../../../../../internal/application/service/testdata/schema_wiki_contract_vector.json',
  import.meta.url,
), 'utf8')) as {
  contract: string
  release: { members: Array<Record<string, unknown>> }
  schema_pack: Record<string, unknown>
  citations: Array<Record<string, unknown>>
}

interface MedicalReleaseEnvelope {
  candidate_evidence_authority: Record<string, unknown>
  release: Record<string, unknown>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseMedicalReleaseEnvelope(value: unknown): MedicalReleaseEnvelope {
  if (
    !isRecord(value)
    || Object.keys(value).sort().join(',') !== 'candidate_evidence_authority,release'
    || !isRecord(value.candidate_evidence_authority)
    || !isRecord(value.release)
  ) {
    throw new Error('SCHEMA_WIKI_RELEASE_VECTOR_ENVELOPE_INVALID')
  }
  return {
    candidate_evidence_authority: value.candidate_evidence_authority,
    release: value.release,
  }
}

function loadMedicalReleaseEnvelope(): MedicalReleaseEnvelope {
  return parseMedicalReleaseEnvelope(JSON.parse(readFileSync(new URL(
    '../../../../../internal/application/service/testdata/schema_wiki_release_596_1_vector.json',
    import.meta.url,
  ), 'utf8')))
}

function loadMedicalReleaseVector(): Record<string, unknown> {
  return loadMedicalReleaseEnvelope().release
}

function records(value: unknown): Array<Record<string, unknown>> {
  assert.equal(Array.isArray(value), true)
  return value as Array<Record<string, unknown>>
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
    unknown_reason: null,
    field_page_sha256: H('f'),
  }
}

function currentEntityVersion() {
  return {
    version: 'schema-wiki-current-entity-version.v1',
    entity_id: 'entity-596-1',
    entity_version_id: 'entity-version-596-1',
    active_release_id: 'release-596-1-active',
    activation_epoch: 4,
    root: {
      contract: 'schema-root-page.v1',
      domain_id: 'medical-insurance',
      domain_sha256: H('1'),
      schema_pack_id: 'medical-596-1-schema67',
      schema_version: '67',
      schema_pack_sha256: H('2'),
      entity_id: 'entity-596-1',
      entity_version_id: 'entity-version-596-1',
      product_version_id: 'product-version-596-1',
      taxonomy_version: 'taxonomy-596-1-v1',
      taxonomy_sha256: H('3'),
      product_display_name: '平安e生保医疗险',
      ordered_section_ids: ['identity', 'coverage'],
      root_page_sha256: H('4'),
    },
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
  assert.throws(
    () => Object.defineProperty(scope, 'raw_kb_id', { value: 'raw-foreign' }),
    TypeError,
  )
})

test('current entity-version is exact, path-pinned, immutable, and requires an active epoch', () => {
  const expected = { entityId: 'entity-596-1', entityVersionId: 'entity-version-596-1' }
  const exact = currentEntityVersion()
  const current = parseSchemaWikiCurrentEntityVersion(exact, expected)

  assert.equal(current.active_release_id, 'release-596-1-active')
  assert.equal(current.activation_epoch, 4)
  assert.equal(current.root.root_page_sha256, H('4'))
  assert.equal(Object.isFrozen(current), true)
  assert.equal(Object.isFrozen(current.root), true)
  assert.equal(Object.isFrozen(current.root.ordered_section_ids), true)

  for (const value of [
    { ...exact, extra: true },
    { ...exact, entity_id: 'entity-foreign' },
    { ...exact, entity_version_id: 'entity-version-foreign' },
    { ...exact, active_release_id: 'current' },
    { ...exact, active_release_id: 'latest' },
    { ...exact, activation_epoch: 0 },
    { ...exact, activation_epoch: 1.5 },
    { ...exact, root: { ...exact.root, entity_id: 'entity-foreign' } },
    { ...exact, root: { ...exact.root, ordered_section_ids: ['identity', 'identity'] } },
    { ...exact, root: { ...exact.root, source_refs: ['generic'] } },
  ]) {
    assert.throws(() => parseSchemaWikiCurrentEntityVersion(value, expected))
  }
})

test('generic Wiki source_refs cannot be parsed as a formal Schema field page', () => {
  assert.throws(() => parseSchemaFieldPage({
    ...presentField(),
    source_refs: ['knowledge-terms|terms.pdf'],
  }, { fieldId: 'field-a', fieldPageSha256: H('f') }), {
    message: 'SCHEMA_FIELD_PAGE_INVALID',
  })
})

test('the frozen medical release projects exactly one root, seven ordered sections, and 67 unique field pages', () => {
  const release = loadMedicalReleaseVector()
  const pack = parseSchemaPack(release.schema_pack)
  const members = records(release.members)
  const roots = members.filter(member => member.member_kind === 'root')
  const sections = members.filter(member => member.member_kind === 'section')
  const fields = members.filter(member => member.member_kind === 'field')
  const fieldIds = fields.map(member => member.field_id)

  assert.equal(members.length, 75)
  assert.equal(roots.length, 1)
  assert.equal(sections.length, 7)
  assert.equal(fields.length, 67)
  assert.deepEqual(
    sections.map(member => member.section_id),
    pack.sections.map(section => section.section_id),
  )
  assert.deepEqual(fieldIds, pack.ordered_field_ids)
  assert.equal(new Set(fieldIds).size, 67)
  assert.equal(fields.every(member => typeof member.payload_sha256 === 'string'), true)
  assert.equal(JSON.stringify(release).includes('source_refs'), false)
  assert.equal(members.some(member => member.member_kind === 'generic'), false)
})

test('the medical fixture rejects missing, extra, or malformed envelope authority', () => {
  const exact = loadMedicalReleaseEnvelope()
  assert.equal(typeof exact.candidate_evidence_authority.contract, 'string')
  assert.equal(typeof exact.release.contract, 'string')

  for (const invalid of [
    { release: exact.release },
    { candidate_evidence_authority: exact.candidate_evidence_authority },
    { ...exact, foreign_authority: true },
    { ...exact, release: null },
    { ...exact, candidate_evidence_authority: [] },
  ]) {
    assert.throws(() => parseMedicalReleaseEnvelope(invalid), {
      message: 'SCHEMA_WIKI_RELEASE_VECTOR_ENVELOPE_INVALID',
    })
  }
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
    unknown_reason: 'NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS',
  }

  const parsed = parseSchemaFieldPage(unknown, {
    fieldId: 'field-a',
    fieldPageSha256: H('f'),
  })
  assert.equal(parsed.state, 'unknown')
  assert.equal(parsed.unknown_reason, 'NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS')
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

  for (const invalid of [
    { ...unknown, unknown_reason: null },
    { ...unknown, unknown_reason: '待人工判断' },
    Object.fromEntries(Object.entries(unknown).filter(([key]) => key !== 'unknown_reason')),
  ]) {
    assert.throws(() => parseSchemaFieldPage(invalid, {
      fieldId: 'field-a', fieldPageSha256: H('f'),
    }))
  }
  assert.throws(() => parseSchemaFieldPage({
    ...presentField(),
    unknown_reason: 'NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS',
  }, { fieldId: 'field-a', fieldPageSha256: H('f') }))
})

test('A1 v2 field payloads carry the closed unknown reason without free-text authority', () => {
  assert.equal(vector.contract, 'schema-wiki-contract-vector.v2')
  const fields = vector.release.members.filter(member => member.member_kind === 'field')
  assert.equal(fields.length, 3)

  for (const member of fields) {
    assert.equal(isRecord(member.payload), true)
    const payload = member.payload as Record<string, unknown>
    const parsed = parseSchemaFieldPage(payload, {
      fieldId: member.field_id as string,
      fieldPageSha256: member.payload_sha256 as string,
    })
    assert.equal(
      parsed.unknown_reason,
      parsed.state === 'unknown' ? 'NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS' : null,
    )
  }
})

test('every known state requires both a formal citation and a 057 receipt', () => {
  for (const state of ['present', 'absent_explicitly'] as const) {
    assert.throws(() => parseSchemaFieldPage({
      ...presentField(),
      state,
      citations: [],
      evidence_receipt_sha256s: [],
    }, { fieldId: 'field-a', fieldPageSha256: H('f') }), {
      message: state === 'absent_explicitly'
        ? 'EXPLICIT_ABSENCE_EVIDENCE_REQUIRED'
        : 'SCHEMA_FIELD_PAGE_INVALID',
    })
  }
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
