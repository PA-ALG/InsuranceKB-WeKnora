import assert from 'node:assert/strict'
import test from 'node:test'

import {
  assertMedicalSchema67Presentation,
  MEDICAL_SCHEMA67_FIELD_PRESENTATION_ROWS,
  resolveSchemaWikiMvpExperience,
} from './schemaWikiMvpPresentation.ts'

const ENTRY_KB = 'b1f1764c-443d-46b8-98e3-d5aa5e55eb42'
const SERVING_KB = '8d5695de-f255-42d5-9a41-042ba86e97b9'

test('the MVP runtime maps only the exact configured material entry to the serving Wiki', () => {
  const config = {
    SCHEMA_WIKI_MVP_ENTRY_KB_ID: ENTRY_KB,
    SCHEMA_WIKI_MVP_SERVING_KB_ID: SERVING_KB,
    SCHEMA_WIKI_MVP_LABEL: '当前 MVP · 只读',
  }

  assert.deepEqual(resolveSchemaWikiMvpExperience(ENTRY_KB, config), {
    entryKnowledgeBaseId: ENTRY_KB,
    servingKnowledgeBaseId: SERVING_KB,
    active: true,
    label: '当前 MVP · 只读',
  })
  assert.deepEqual(resolveSchemaWikiMvpExperience('unrelated-kb', config), {
    entryKnowledgeBaseId: 'unrelated-kb',
    servingKnowledgeBaseId: 'unrelated-kb',
    active: false,
    label: null,
  })
})

test('invalid or half-configured runtime values never redirect a knowledge base', () => {
  for (const config of [
    {},
    { SCHEMA_WIKI_MVP_ENTRY_KB_ID: ENTRY_KB },
    { SCHEMA_WIKI_MVP_SERVING_KB_ID: SERVING_KB },
    {
      SCHEMA_WIKI_MVP_ENTRY_KB_ID: '../foreign',
      SCHEMA_WIKI_MVP_SERVING_KB_ID: SERVING_KB,
    },
    {
      SCHEMA_WIKI_MVP_ENTRY_KB_ID: ENTRY_KB,
      SCHEMA_WIKI_MVP_SERVING_KB_ID: 'foreign/kb',
    },
  ]) {
    assert.deepEqual(resolveSchemaWikiMvpExperience(ENTRY_KB, config), {
      entryKnowledgeBaseId: ENTRY_KB,
      servingKnowledgeBaseId: ENTRY_KB,
      active: false,
      label: null,
    })
  }
})

test('the frozen presentation is exactly 67 Chinese-primary fields', () => {
  const fieldIds = MEDICAL_SCHEMA67_FIELD_PRESENTATION_ROWS.map(([fieldId]) => fieldId)
  const presentation = assertMedicalSchema67Presentation(fieldIds)

  assert.equal(MEDICAL_SCHEMA67_FIELD_PRESENTATION_ROWS.length, 67)
  assert.equal(presentation.size, 67)
  assert.equal(presentation.get('sales_status'), '销售状态')
  assert.equal(presentation.get('entry_age_range'), '投保年龄')
  assert.equal(presentation.get('sales_pitch_script'), 'Pitch话术')
  for (const [fieldId, displayName] of MEDICAL_SCHEMA67_FIELD_PRESENTATION_ROWS) {
    assert.match(fieldId, /^[a-z][a-z0-9_]*$/)
    assert.match(displayName, /[\u3400-\u9fff]/)
  }
})

test('missing, extra, duplicate and reordered field topology fails closed', () => {
  const exact = MEDICAL_SCHEMA67_FIELD_PRESENTATION_ROWS.map(([fieldId]) => fieldId)
  const reordered = [...exact]
  ;[reordered[0], reordered[1]] = [reordered[1], reordered[0]]

  for (const invalid of [
    exact.slice(0, -1),
    [...exact, 'unexpected_field'],
    [...exact.slice(0, -1), exact[0]],
    reordered,
  ]) {
    assert.throws(() => assertMedicalSchema67Presentation(invalid), {
      message: 'SCHEMA_WIKI_MVP_PRESENTATION_TOPOLOGY_INVALID',
    })
  }
})
