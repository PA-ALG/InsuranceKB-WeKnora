import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  assertGoldenSummaryDossierJoin,
  goldenQualityStatusPresentation,
  parseSchemaWikiGoldenQualityDossier,
  parseSchemaWikiGoldenQualitySummary,
} from './schemaWikiGoldenQualityContract.ts'
import {
  bootstrapSchemaWikiClient,
  type SchemaWikiReadTransport,
} from '../../../api/schema-wiki/index.ts'

const H = (value: string) => value.repeat(64)
const bundle = JSON.parse(readFileSync(new URL(
  '../../../../../harness/tests/fixtures/schema67_golden_evaluation_bundle_596_1.json',
  import.meta.url,
), 'utf8')) as Record<string, unknown>
const evaluationId = bundle.evaluation_id as string
const receipt = bundle.quality_gate_receipt as Record<string, unknown>
const preparationId = 'preparation-596-1'

function summary(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    version: 'schema-wiki-golden-quality-summary.v1',
    preparation_id: preparationId,
    evaluation_id: evaluationId,
    quality_gate_receipt_sha256: receipt.receipt_sha256,
    public_aggregate: structuredClone(bundle.public_aggregate),
    evaluation_bundle_sha256: bundle.evaluation_bundle_sha256,
    wiki_admission_allowed: false,
    serving_effect: 'NONE',
    ...overrides,
  }
}

function dossier(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    version: 'schema-wiki-golden-quality-dossier.v1',
    preparation_id: preparationId,
    evaluation_id: evaluationId,
    quality_gate_receipt_sha256: receipt.receipt_sha256,
    private_dossier: structuredClone(bundle.private_dossier),
    evaluation_bundle_sha256: bundle.evaluation_bundle_sha256,
    serving_effect: 'NONE',
    ...overrides,
  }
}

const expected = Object.freeze({ preparationId, evaluationId })

test('preparation summary is the closed public aggregate wrapper and never grants serving', () => {
  const parsed = parseSchemaWikiGoldenQualitySummary(summary(), expected)
  assert.equal(parsed.public_aggregate.status, 'PASS')
  assert.equal(parsed.public_aggregate.metrics.length, 15)
  assert.equal(parsed.wiki_admission_allowed, false)
  assert.equal(parsed.serving_effect, 'NONE')
  assert.equal('field_decisions' in parsed.public_aggregate, false)

  assert.throws(
    () => parseSchemaWikiGoldenQualitySummary(summary({ fields: [] }), expected),
    /GOLDEN_QUALITY_SUMMARY_INVALID/,
  )
  assert.throws(
    () => parseSchemaWikiGoldenQualitySummary(summary({ wiki_admission_allowed: true }), expected),
    /GOLDEN_QUALITY_SUMMARY_INVALID/,
  )
})

test('safe status presentation never makes a non-PASS result preparation-readable', () => {
  assert.deepEqual(goldenQualityStatusPresentation('PASS'), {
    status: 'PASS', readable: true, label: 'Quality gate passed',
  })
  for (const status of ['FAIL', 'FIXTURE_ONLY', 'INCONCLUSIVE'] as const) {
    const presentation = goldenQualityStatusPresentation(status)
    assert.equal(presentation.status, status)
    assert.equal(presentation.readable, false)
  }
  assert.throws(() => goldenQualityStatusPresentation('PENDING'), /GOLDEN_QUALITY_STATUS_INVALID/)

  const aggregate = structuredClone(bundle.public_aggregate) as Record<string, unknown>
  aggregate.status = 'FIXTURE_ONLY'
  assert.throws(
    () => parseSchemaWikiGoldenQualitySummary(summary({ public_aggregate: aggregate }), expected),
    /GOLDEN_QUALITY_SUMMARY_INVALID/,
  )
})

test('private dossier preserves exact ordered67 decisions and ordered15 metrics', () => {
  const parsed = parseSchemaWikiGoldenQualityDossier(dossier(), expected)
  assert.equal(parsed.private_dossier.field_decisions.length, 67)
  assert.equal(parsed.private_dossier.metrics.length, 15)
  assert.equal(new Set(parsed.private_dossier.field_decisions.map(row => row.field_id)).size, 67)
  assert.equal(parsed.private_dossier.field_decisions.filter(row => row.candidate_state === 'unknown').length, 21)

  const privateDossier = structuredClone(bundle.private_dossier) as Record<string, unknown>
  const rows = privateDossier.field_decisions as Array<Record<string, unknown>>
  ;[rows[0], rows[1]] = [rows[1], rows[0]]
  assert.throws(
    () => parseSchemaWikiGoldenQualityDossier(dossier({ private_dossier: privateDossier }), expected),
    /GOLDEN_QUALITY_DOSSIER_INVALID/,
  )
})

test('summary, dossier, and evidence preview client routes are exact preparation routes', async () => {
  const paths: string[] = []
  const transport: SchemaWikiReadTransport = {
    async get(path: string): Promise<unknown> {
      paths.push(path)
      if (path.endsWith('/schema-scope')) {
        return {
          version: 'schema-wiki-scope.v1',
          space_id: 'space-a',
          raw_kb_id: 'raw-a',
          wiki_kb_id: 'wiki-a',
          scope_sha256: H('a'),
        }
      }
      return { ok: true }
    },
  }
  const client = await bootstrapSchemaWikiClient('wiki-a', transport)
  await client.getGoldenQualitySummary(preparationId, evaluationId)
  await client.getGoldenQualityDossier(preparationId, evaluationId)
  await client.getGoldenEvidencePreview(preparationId, evaluationId, 'product_code', H('b'))

  const base = '/api/v1/knowledgebase/wiki-a/wiki/release-scopes/space-a/raw/raw-a/schema'
  assert.deepEqual(paths.slice(1), [
    `${base}/preparations/${preparationId}/golden-quality/evaluations/${evaluationId}/summary`,
    `${base}/preparations/${preparationId}/golden-quality/evaluations/${evaluationId}/dossier`,
    `${base}/preparations/${preparationId}/golden-quality/evaluations/${evaluationId}`
      + `/fields/product_code/evidence/${H('b')}/preview`,
  ])
  assert.doesNotMatch(paths.join('\n'), /\/current|\/latest|page=1|\/materials/)
})

test('identity drift and wrapper hash substitution fail closed', () => {
  assert.throws(
    () => parseSchemaWikiGoldenQualitySummary(summary({ preparation_id: 'foreign' }), expected),
    /GOLDEN_QUALITY_SUMMARY_INVALID/,
  )
  const parsedSummary = parseSchemaWikiGoldenQualitySummary(summary(), expected)
  const parsedDossier = parseSchemaWikiGoldenQualityDossier(
    dossier({ evaluation_bundle_sha256: H('f') }), expected,
  )
  assert.throws(
    () => assertGoldenSummaryDossierJoin(parsedSummary, parsedDossier),
    /GOLDEN_QUALITY_IDENTITY_MISMATCH/,
  )
})
