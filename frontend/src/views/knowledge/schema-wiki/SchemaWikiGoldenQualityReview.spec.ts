// @vitest-environment happy-dom

import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import type { SchemaWikiClient } from '../../../api/schema-wiki/index.ts'
import SchemaWikiGoldenQualityReview from './SchemaWikiGoldenQualityReview.vue'

const H = (value: string) => value.repeat(64)
const bundle = JSON.parse(readFileSync(resolve(
  process.cwd(), '../harness/tests/fixtures/schema67_golden_evaluation_bundle_596_1.json',
), 'utf8')) as Record<string, unknown>
const successorStatus = JSON.parse(readFileSync(resolve(
  process.cwd(), '../internal/types/testdata/schema_wiki_golden_successor_status_596_1.json',
), 'utf8')) as Record<string, unknown>
const receipt = bundle.quality_gate_receipt as Record<string, unknown>
const preparationId = 'preparation-596-1'
const evaluationId = bundle.evaluation_id as string
const previewBytes = new TextEncoder().encode('%PDF-1.7\nreview\n%%EOF')
const fileSHA256 = createHash('sha256').update(previewBytes).digest('hex')

function summary(): Record<string, unknown> {
  return {
    version: 'schema-wiki-golden-quality-summary.v1',
    preparation_id: preparationId,
    evaluation_id: evaluationId,
    quality_gate_receipt_sha256: receipt.receipt_sha256,
    public_aggregate: structuredClone(bundle.public_aggregate),
    evaluation_bundle_sha256: bundle.evaluation_bundle_sha256,
    wiki_admission_allowed: false,
    serving_effect: 'NONE',
  }
}

function dossier(): Record<string, unknown> {
  return {
    version: 'schema-wiki-golden-quality-dossier.v1',
    preparation_id: preparationId,
    evaluation_id: evaluationId,
    quality_gate_receipt_sha256: receipt.receipt_sha256,
    private_dossier: structuredClone(bundle.private_dossier),
    evaluation_bundle_sha256: bundle.evaluation_bundle_sha256,
    serving_effect: 'NONE',
  }
}

function previewAuthority(): Record<string, unknown> {
  return {
    contract: 'schema-wiki-golden-evidence-preview-authority.v1',
    token_key_id: 'golden-preview-key',
    preparation_id: preparationId,
    evaluation_id: evaluationId,
    candidate_sha256: (bundle.private_dossier as Record<string, unknown>).candidate_sha256,
    field_id: 'product_code',
    evidence_id: H('e'),
    revision_source: {
      contract: 'live-revision-source-receipt.v1',
      revision_source_id: H('1'),
      tenant_id: 10003,
      space_id: 'space-a',
      raw_kb_id: 'raw-a',
      wiki_kb_id: 'wiki-a',
      knowledge_id: 'knowledge-terms',
      evidence_parse_attempt_id: 'attempt-terms',
      weknora_parse_attempt: 1,
      resource_id: 'resource-terms',
      file_sha256: fileSHA256,
      size: previewBytes.byteLength,
      mime_type: 'application/pdf',
      page_count: 39,
      parsed_document_sha256: H('2'),
      parse_manifest_sha256: H('3'),
      weknora_manifest_algorithm: 'weknora.chunk_manifest.v1',
      weknora_manifest_digest: H('4'),
      weknora_chunk_count: 8,
      source_receipt_sha256: H('5'),
    },
    citation_sha256: H('6'),
    binding_sha256: H('7'),
    evidence_receipt_sha256: H('8'),
    page_number: 12,
    bbox: {
      coordinate_system: 'normalized_0_1e6',
      page_width: 1_000_000,
      page_height: 1_000_000,
      x0: 100_000,
      y0: 200_000,
      x1: 400_000,
      y1: 300_000,
    },
    quote_sha256: H('9'),
    content_snapshot_sha256: H('a'),
    coordinate_space_version: 'normalized_0_1e6',
    page_width: 1_000_000,
    page_height: 1_000_000,
    rotation_degrees: 0,
    retention_state: 'pinned',
    expires_at_unix: 1786442400,
    authority_sha256: H('b'),
    opaque_token: 'golden.payload.signature',
  }
}

function client(overrides: Partial<SchemaWikiClient> = {}): SchemaWikiClient {
  return {
    scope: {
      version: 'schema-wiki-scope.v1',
      space_id: 'space-596-1', raw_kb_id: 'raw-kb-596-1',
      wiki_kb_id: 'wiki-kb-596-1', scope_sha256: H('c'),
    },
    getDomains: vi.fn(), getCurrentTaxonomy: vi.fn(), getCurrentEntityVersion: vi.fn(),
    getReleaseRoot: vi.fn(), getReleaseSection: vi.fn(), getReleaseField: vi.fn(),
    getPreparationRoot: vi.fn(), getPreparationSection: vi.fn(), getPreparationField: vi.fn(),
    getGoldenQualitySummary: vi.fn(async () => summary()),
    getGoldenQualityDossier: vi.fn(async () => dossier()),
    getGoldenEvidencePreview: vi.fn(async () => previewAuthority()),
    getGoldenSuccessorStatus: vi.fn(async () => structuredClone(successorStatus)),
    ...overrides,
  }
}

const pdfPort = () => ({
  open: vi.fn(async () => ({
    pageCount: 39,
    renderPage: vi.fn(async (pageNumber: number) => ({
      pageNumber,
      width: 800,
      height: 1200,
      canvas: document.createElement('canvas'),
    })),
  })),
})

describe('SchemaWikiGoldenQualityReview', () => {
  it('renders completed linyao review, COMPLETE_67, and only the receipt blocker', async () => {
    const wrapper = mount(SchemaWikiGoldenQualityReview, {
      props: {
        client: client(), preparationId, evaluationId,
        getBytesByToken: vi.fn(), pdfPort: pdfPort(),
      },
    })
    await vi.waitFor(() => expect(wrapper.find('[data-testid="golden-review-summary"]').exists()).toBe(true))
    expect(wrapper.get('[data-testid="golden-review-reviewed-by"]').text()).toContain('linyao')
    expect(wrapper.get('[data-testid="golden-review-annotator"]').text()).toContain('claude-fable-5')
    expect(wrapper.get('[data-testid="golden-review-reviewed-at"]').text()).toContain('UNKNOWN')
    expect(wrapper.get('[data-testid="golden-review-attestor"]').text()).toContain('workspace-owner-houjing')
    expect(wrapper.get('[data-testid="golden-review-mapping"]').text()).toMatch(/67.*0/)
    expect(wrapper.get('[data-testid="golden-review-admission"]').text()).toMatch(/BLOCKED.*UNVERIFIED/)
    expect(wrapper.findAll('[data-testid="golden-review-field-row"]')).toHaveLength(0)
    expect(wrapper.findAll('[data-testid="golden-review-residual-row"]')).toHaveLength(0)
    expect(wrapper.text()).not.toMatch(/residual|待人工|待审核|pending/i)
    expect(wrapper.findAll('[data-testid="golden-review-evidence-preview"]')).toHaveLength(0)
    expect(wrapper.text()).not.toMatch(/67字段.*待标注|无人Review/)
    expect(wrapper.get('[data-testid="golden-review-admission"]').text()).toContain(
      'GOLDEN_APPROVAL_RECEIPT_UNVERIFIED',
    )
    for (const action of ['draft', 'publish', 'activate']) {
      expect(wrapper.find(`[data-testid="golden-review-${action}"]`).exists()).toBe(false)
    }
  })

  it('renders the PASS aggregate, exact67 comparisons, exact15 metrics, and no authority controls', async () => {
    const wrapper = mount(SchemaWikiGoldenQualityReview, {
      props: {
        client: client(), preparationId, evaluationId,
        getBytesByToken: vi.fn(), pdfPort: pdfPort(),
      },
    })
    await vi.waitFor(() => expect(wrapper.findAll('[data-testid="golden-field-row"]')).toHaveLength(67))
    expect(wrapper.findAll('[data-testid="golden-metric-row"]')).toHaveLength(15)
    expect(wrapper.get('[data-testid="golden-quality-status"]').text()).toContain('PASS')
    expect(wrapper.get('[data-testid="golden-field-row"]').text()).toContain('present')
    expect(wrapper.text()).not.toMatch(/approve|CreateDraft|publish|activate/i)
    expect(wrapper.text()).not.toContain('45/1/21')
  })

  it('uses only the exact field/evidence route, opaque token bytes, exact page, and bbox overlay', async () => {
    const getGoldenEvidencePreview = vi.fn(async () => previewAuthority())
    const getBytesByToken = vi.fn(async () => previewBytes)
    const port = pdfPort()
    const wrapper = mount(SchemaWikiGoldenQualityReview, {
      props: {
        client: client({ getGoldenEvidencePreview }), preparationId, evaluationId,
        evidenceSelection: { field_id: 'product_code', evidence_id: H('e') },
        getBytesByToken,
        pdfPort: port,
      },
    })
    await vi.waitFor(() => expect(wrapper.find('[data-testid="golden-evidence-page"]').exists()).toBe(true))
    expect(getGoldenEvidencePreview).toHaveBeenCalledWith(
      preparationId, evaluationId, 'product_code', H('e'),
    )
    expect(getBytesByToken).toHaveBeenCalledWith('golden.payload.signature')
    expect(port.open).toHaveBeenCalledOnce()
    expect(wrapper.get('[data-testid="golden-evidence-page"]').attributes('data-page-number')).toBe('12')
    expect(wrapper.get('[data-testid="golden-evidence-highlight"]').attributes('style')).toContain('left: 80px')
  })

  it('shows typed unavailable without token, bytes, PdfPort, or private error leakage', async () => {
    const getGoldenEvidencePreview = vi.fn(async () => { throw new Error('private /tmp/raw.pdf') })
    const getBytesByToken = vi.fn()
    const port = pdfPort()
    const wrapper = mount(SchemaWikiGoldenQualityReview, {
      props: {
        client: client({ getGoldenEvidencePreview }), preparationId, evaluationId,
        evidenceSelection: { field_id: 'product_code', evidence_id: H('e') },
        getBytesByToken, pdfPort: port,
      },
    })
    await vi.waitFor(() => expect(wrapper.find('[data-testid="golden-evidence-error"]').exists()).toBe(true))
    expect(wrapper.get('[data-testid="golden-evidence-error"]').text()).toBe('GOLDEN_EVIDENCE_UNAVAILABLE')
    expect(wrapper.text()).not.toContain('/tmp/raw.pdf')
    expect(getBytesByToken).not.toHaveBeenCalled()
    expect(port.open).not.toHaveBeenCalled()
  })

  it('fails closed on preparation permissions without exposing dossier content', async () => {
    const getGoldenQualityDossier = vi.fn(async () => { throw new Error('foreign reviewer secret') })
    const wrapper = mount(SchemaWikiGoldenQualityReview, {
      props: {
        client: client({ getGoldenQualityDossier }), preparationId, evaluationId,
        getBytesByToken: vi.fn(), pdfPort: pdfPort(),
      },
    })
    await vi.waitFor(() => expect(wrapper.find('[data-testid="golden-quality-error"]').exists()).toBe(true))
    expect(wrapper.get('[data-testid="golden-quality-error"]').text()).toBe('尚无有效语义质量结论')
    expect(wrapper.findAll('[data-testid="golden-field-row"]')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('foreign reviewer secret')
  })
})
