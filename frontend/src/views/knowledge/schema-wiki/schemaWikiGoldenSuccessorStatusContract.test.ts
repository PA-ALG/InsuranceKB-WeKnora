import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  goldenSuccessorStatusPresentation,
  parseSchemaWikiGoldenSuccessorStatus,
} from './schemaWikiGoldenSuccessorStatusContract.ts'

const authority = JSON.parse(readFileSync(new URL(
  '../../../../../internal/types/testdata/schema_wiki_golden_successor_status_596_1.json',
  import.meta.url,
), 'utf8')) as Record<string, unknown>
const expectedScope = Object.freeze({
  spaceId: 'space-596-1',
  rawKbId: 'raw-kb-596-1',
  wikiKbId: 'wiki-kb-596-1',
})

test('exact COMPLETE_67 authority presents three independent status layers', async () => {
  const exact = await parseSchemaWikiGoldenSuccessorStatus(
    structuredClone(authority),
    expectedScope,
  )
  const result = goldenSuccessorStatusPresentation(exact)

  assert.deepEqual(result.sourceReview, {
    status: 'COMPLETED',
    reviewedBy: 'linyao',
    reviewedAtLabel: 'UNKNOWN',
    annotatorModelId: 'claude-fable-5',
    attestedBy: 'workspace-owner-houjing',
  })
  assert.deepEqual(result.mapping, {
    status: 'COMPLETE_67',
    closedCount: 67,
    residualCount: 0,
    orderedResidualFieldIds: [],
  })
  assert.deepEqual(result.admission, {
    status: 'BLOCKED_RECEIPT_UNVERIFIED',
    readyToSignStatus: 'READY_TO_SIGN',
    receiptStatus: 'UNVERIFIED',
    blockingReasonCodes: ['GOLDEN_APPROVAL_RECEIPT_UNVERIFIED'],
  })
})

test('coverage unknowns are not residual, pending, or an action blocker', async () => {
  const result = goldenSuccessorStatusPresentation(
    await parseSchemaWikiGoldenSuccessorStatus(structuredClone(authority), expectedScope),
  )
  const wire = JSON.stringify(result)

  assert.doesNotMatch(wire, /coverageGaps|candidate_value|evidence_id|citation|preview|page_number|page.?1/i)
  assert.doesNotMatch(wire, /SCHEMA67_RESIDUALS_PENDING|UNKNOWN_FIELD_BLOCKED/)
  assert.deepEqual(result.admission.blockingReasonCodes, ['GOLDEN_APPROVAL_RECEIPT_UNVERIFIED'])
  assert.equal('actions' in result, false)
})

test('closed parser rejects superseded, missing, count, scope, and formal Dossier drift', async () => {
  const missing = structuredClone(authority)
  delete missing.mapping_sha256
  const cases = [
    { ...structuredClone(authority), extra: 'forbidden' },
    missing,
    {
      ...structuredClone(authority),
      schema67_mapping_status: 'PARTIAL_51_CLOSED_16_RESIDUAL',
      closed_count: 51,
      residual_count: 16,
      residual_field_ids: Array.from({ length: 16 }, (_, index) => `superseded-${index}`),
      golden_admission_status: 'BLOCKED_RESIDUALS_AND_RECEIPT_UNVERIFIED',
      ready_to_sign_status: 'READY_TO_SIGN_AFTER_RESIDUAL_CLOSURE',
      status_sha256: 'e'.repeat(64),
    },
    { ...structuredClone(authority), closed_count: 66 },
    { ...structuredClone(authority), residual_count: 1, residual_field_ids: ['foreign-field'] },
    { ...structuredClone(authority), space_id: 'foreign-space' },
    {
      version: 'schema-wiki-golden-quality-dossier.v2',
      review_successor: { human_review_layer: { receipt_status: 'VERIFIED' } },
    },
  ]
  for (const payload of cases) {
    await assert.rejects(
      () => parseSchemaWikiGoldenSuccessorStatus(payload, expectedScope),
      /GOLDEN_SUCCESSOR_STATUS_INVALID/,
    )
  }
})
