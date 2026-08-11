import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  assertPinnedCitation,
  citationHighlightStyle,
  parseCitationTarget,
  type CitationPinV1,
  type CitationTargetV1,
} from './schemaCitationTarget.ts'
import * as citationTargetContract from './schemaCitationTarget.ts'

const H = (character: string) => character.repeat(64)

interface ImmutableRevisionPreviewRequestV1 {
  readonly release_id: string
  readonly activation_epoch: number
  readonly field_id: string
  readonly citation_id: string
}

interface ImmutableRevisionPreviewV1 {
  readonly contract: 'schema-wiki-citation-content-authority.v1'
  readonly token_key_id: string
  readonly release_id: string
  readonly activation_epoch: number
  readonly field_id: string
  readonly citation_id: string
  readonly revision_source: {
    readonly contract: 'live-revision-source-receipt.v1'
    readonly revision_source_id: string
    readonly tenant_id: number
    readonly space_id: string
    readonly raw_kb_id: string
    readonly wiki_kb_id: string
    readonly knowledge_id: string
    readonly evidence_parse_attempt_id: string
    readonly weknora_parse_attempt: number
    readonly resource_id: string
    readonly file_sha256: string
    readonly size: number
    readonly mime_type: 'application/pdf'
    readonly page_count: number
    readonly parsed_document_sha256: string
    readonly parse_manifest_sha256: string
    readonly weknora_manifest_algorithm: string
    readonly weknora_manifest_digest: string
    readonly weknora_chunk_count: number
    readonly source_receipt_sha256: string
  }
  readonly candidate_sha256: string
  readonly citation_sha256: string
  readonly binding_sha256: string
  readonly page_number: number
  readonly bbox: CitationTargetV1['bbox']
  readonly quote_sha256: string
  readonly content_snapshot_sha256: string
  readonly coordinate_space_version: 'normalized_0_1e6'
  readonly page_width: number
  readonly page_height: number
  readonly rotation_degrees: 0 | 90 | 180 | 270
  readonly retention_state: 'pinned'
  readonly expires_at_unix: number
  readonly opaque_token: string
  readonly authority_sha256: string
}

const immutablePreviewContract = citationTargetContract as unknown as {
  parseSchemaWikiCitationContentAuthorityV1(
    value: unknown,
    expected: ImmutableRevisionPreviewRequestV1,
  ): ImmutableRevisionPreviewV1
  citationPreviewHighlightStyle(
    preview: ImmutableRevisionPreviewV1,
    viewport: { width: number; height: number },
  ): { left: number; top: number; width: number; height: number }
}
const vector = JSON.parse(readFileSync(new URL(
  '../../../../internal/application/service/testdata/schema_wiki_contract_vector.json',
  import.meta.url,
), 'utf8')) as {
  citations: Array<Record<string, unknown>>
  release: { citation_bindings: Array<Record<string, string>> }
}

function citation(pageNumber = 12): Record<string, unknown> {
  const exact = structuredClone(vector.citations[0])
  if (pageNumber === 12) return exact
  return {
    ...exact,
    citation_id: `citation-page-${pageNumber}`,
    citation_sha256: H('c'),
    chunk_id: `chunk-page-${pageNumber}`,
    locator_ref: `block-page-${pageNumber}`,
    page_number: pageNumber,
  }
}

function pin(target: CitationTargetV1): CitationPinV1 {
  const binding = vector.release.citation_bindings[0]
  return {
    release_id: 'release-r1',
    field_id: 'field-a',
    logical_member_ref: target.logical_member_ref,
    member_digest: binding.member_digest,
    citation_binding: {
      contract: 'citation-member-binding.v1',
      citation_sha256: binding.citation_sha256,
      logical_member_ref: binding.logical_member_ref,
      member_digest: binding.member_digest,
      binding_sha256: binding.binding_sha256,
    },
    space_id: target.space_id,
    entity_version_id: target.entity_version_id,
    knowledge_id: target.knowledge_id,
    chunk_id: target.chunk_id,
    source_revision_id: target.source_revision_id,
    parse_attempt_id: target.parse_attempt_id,
    parsed_document_sha256: target.parsed_document_sha256,
    parse_manifest_sha256: target.parse_manifest_sha256,
    page_number: target.page_number,
    locator_ref: target.locator_ref,
    quote_snapshot: target.quote_snapshot,
    content_snapshot_sha256: target.content_snapshot_sha256,
  }
}

test('the unchanged A1 vector and independent page 12/page 27 targets parse', () => {
  assert.equal(parseCitationTarget(citation(12)).page_number, 12)
  assert.equal(parseCitationTarget(citation(27)).page_number, 27)
})

test('knowledge-only, current/latest, and control-character references are rejected', () => {
  assert.throws(() => parseCitationTarget({ knowledge_id: 'knowledge-terms' }), {
    message: 'CITATION_TARGET_INCOMPLETE',
  })
  for (const reserved of ['current', 'LATEST']) {
    assert.throws(() => parseCitationTarget({
      ...citation(12),
      source_revision_id: reserved,
    }), { message: 'CITATION_REVISION_NOT_PINNED' })
  }
  assert.throws(() => parseCitationTarget({
    ...citation(12),
    locator_ref: 'block-a\u0000foreign',
  }), { message: 'CITATION_TARGET_INCOMPLETE' })
})

test('missing or zero page is PAGE_UNAVAILABLE and never defaults to page one', () => {
  const { page_number: _page, ...missingPage } = citation(12)
  assert.throws(() => parseCitationTarget(missingPage), { message: 'PAGE_UNAVAILABLE' })
  assert.throws(() => parseCitationTarget({ ...citation(12), page_number: 0 }), {
    message: 'PAGE_UNAVAILABLE',
  })
})

test('invalid, degenerate, full-page, or unknown-coordinate bbox is rejected', () => {
  const base = citation(12)
  assert.throws(() => parseCitationTarget({
    ...base,
    bbox: { coordinate_system: 'pdf_points', page_width: 600, page_height: 800, x0: 300, y0: 200, x1: 300, y1: 400 },
  }), { message: 'BBOX_UNAVAILABLE' })
  assert.throws(() => parseCitationTarget({
    ...base,
    bbox: { coordinate_system: 'pdf_points', page_width: 600, page_height: 800, x0: 0, y0: 0, x1: 600, y1: 800 },
  }), { message: 'BBOX_UNAVAILABLE' })
  assert.throws(() => parseCitationTarget({
    ...base,
    bbox: { coordinate_system: 'unknown', page_width: 600, page_height: 800, x0: 1, y0: 2, x1: 3, y1: 4 },
  }), { message: 'BBOX_UNAVAILABLE' })
})

test('member binding and every replay identity drift fail before preview', () => {
  const exactTarget = parseCitationTarget(citation(12))
  assert.doesNotThrow(() => assertPinnedCitation(exactTarget, pin(exactTarget)))
  assert.throws(() => assertPinnedCitation(exactTarget, {
    ...pin(exactTarget),
    member_digest: H('9'),
  }), { message: 'CITATION_MEMBER_BINDING_MISMATCH' })
  assert.throws(() => assertPinnedCitation(exactTarget, {
    ...pin(exactTarget),
    field_id: 'field-foreign',
  }), { message: 'CITATION_MEMBER_BINDING_MISMATCH' })
  assert.throws(() => assertPinnedCitation(exactTarget, {
    ...pin(exactTarget),
    parse_manifest_sha256: H('9'),
  }), { message: 'CITATION_REPLAY_IDENTITY_MISMATCH' })
})

test('A1 pdf_points bbox transforms to a visible viewport overlay without fallback', () => {
  assert.deepEqual(citationHighlightStyle(parseCitationTarget(citation(12)), {
    width: 600,
    height: 800,
  }), {
    left: 100,
    top: 120,
    width: 260,
    height: 60,
  })
})

function immutablePreview(
  sourceRole: 'terms' | 'brochure' | 'rate_table',
  pageNumber: number,
  pageCount: number,
): Record<string, unknown> {
  const target = citation(pageNumber)
  return {
    contract: 'schema-wiki-citation-content-authority.v1',
    token_key_id: 'citation-token-key-1',
    release_id: 'release-r1',
    activation_epoch: 9,
    field_id: 'field-a',
    citation_id: `citation-${sourceRole}-${pageNumber}`,
    revision_source: {
      contract: 'live-revision-source-receipt.v1',
      revision_source_id: H(sourceRole === 'terms' ? '4' : sourceRole === 'brochure' ? '5' : '6'),
      tenant_id: 10003,
      space_id: target.space_id,
      raw_kb_id: 'raw-596-1',
      wiki_kb_id: 'wiki-596-1',
      knowledge_id: target.knowledge_id,
      evidence_parse_attempt_id: target.parse_attempt_id,
      weknora_parse_attempt: sourceRole === 'terms' ? 2 : 1,
      resource_id: `resource-${sourceRole}`,
      file_sha256: H(sourceRole === 'terms' ? '1' : sourceRole === 'brochure' ? '2' : '3'),
      size: 4096,
      mime_type: 'application/pdf',
      page_count: pageCount,
      parsed_document_sha256: target.parsed_document_sha256,
      parse_manifest_sha256: target.parse_manifest_sha256,
      weknora_manifest_algorithm: 'weknora.chunk_manifest.v1',
      weknora_manifest_digest: H('8'),
      weknora_chunk_count: 8,
      source_receipt_sha256: H('9'),
    },
    candidate_sha256: H('a'),
    citation_sha256: target.citation_sha256,
    binding_sha256: H('b'),
    page_number: pageNumber,
    bbox: {
      coordinate_system: 'normalized_0_1e6',
      page_width: 1_000_000,
      page_height: 1_000_000,
      x0: 100_000,
      y0: 200_000,
      x1: 400_000,
      y1: 300_000,
    },
    quote_sha256: target.quote_sha256,
    content_snapshot_sha256: target.content_snapshot_sha256,
    coordinate_space_version: 'normalized_0_1e6',
    page_width: 1_000_000,
    page_height: 1_000_000,
    rotation_degrees: 0,
    retention_state: 'pinned',
    expires_at_unix: 1786442400,
    opaque_token: `key-${sourceRole}.payload-${pageNumber}.signature-${sourceRole}`,
    authority_sha256: H('7'),
  }
}

function immutableRequest(value: Record<string, unknown>): ImmutableRevisionPreviewRequestV1 {
  return {
    release_id: value.release_id as string,
    activation_epoch: value.activation_epoch as number,
    field_id: value.field_id as string,
    citation_id: value.citation_id as string,
  }
}

test('immutable revision preview v1 closes the active pin and admits exact terms 12 and brochure 27', () => {
  for (const payload of [
    immutablePreview('terms', 12, 39),
    immutablePreview('brochure', 27, 27),
  ]) {
    const parsed = immutablePreviewContract.parseSchemaWikiCitationContentAuthorityV1(
      payload,
      immutableRequest(payload),
    )
    assert.equal(parsed.page_number, payload.page_number)
    assert.equal(parsed.revision_source.page_count, (
      payload.revision_source as Record<string, unknown>
    ).page_count)
    assert.equal(Object.isFrozen(parsed), true)
    assert.equal(Object.isFrozen(parsed.revision_source), true)
    assert.equal(Object.isFrozen(parsed.bbox), true)
  }
})

test('rate-table page 12 or 27 is unavailable before token or byte use', () => {
  for (const pageNumber of [12, 27]) {
    const payload = immutablePreview('rate_table', pageNumber, 2)
    assert.throws(() => immutablePreviewContract.parseSchemaWikiCitationContentAuthorityV1(
      payload,
      immutableRequest(payload),
    ), { message: 'PAGE_UNAVAILABLE' })
  }
})

test('preview DTO rejects pin, hash, coordinate-space, and bbox drift as typed unavailable', () => {
  const payload = immutablePreview('terms', 12, 39)
  assert.throws(() => immutablePreviewContract.parseSchemaWikiCitationContentAuthorityV1(
    { ...payload, release_id: 'release-foreign' },
    immutableRequest(payload),
  ), { message: 'CITATION_REPLAY_IDENTITY_MISMATCH' })
  assert.throws(() => immutablePreviewContract.parseSchemaWikiCitationContentAuthorityV1(
    {
      ...payload,
      revision_source: {
        ...(payload.revision_source as Record<string, unknown>),
        file_sha256: 'not-a-hash',
      },
    },
    immutableRequest(payload),
  ), { message: 'CITATION_PREVIEW_AUTHORITY_INVALID' })
  for (const bbox of [
    { ...(payload.bbox as Record<string, unknown>), coordinate_system: 'unknown' },
    { ...(payload.bbox as Record<string, unknown>), x1: 100_000 },
  ]) {
    assert.throws(() => immutablePreviewContract.parseSchemaWikiCitationContentAuthorityV1(
      {
        ...payload,
        bbox,
      },
      immutableRequest(payload),
    ), { message: 'BBOX_UNAVAILABLE' })
  }
  assert.throws(() => immutablePreviewContract.parseSchemaWikiCitationContentAuthorityV1(
    { ...payload, rotation_degrees: 45 },
    immutableRequest(payload),
  ), { message: 'BBOX_UNAVAILABLE' })
})

test('preview bbox transformation binds coordinate space, source dimensions, and rotation', () => {
  const payload = immutablePreview('brochure', 27, 27)
  const rotated = { ...payload, rotation_degrees: 90 }
  const parsed = immutablePreviewContract.parseSchemaWikiCitationContentAuthorityV1(
    rotated,
    immutableRequest(rotated),
  )
  assert.deepEqual(immutablePreviewContract.citationPreviewHighlightStyle(parsed, {
    width: 1000,
    height: 1000,
  }), {
    left: 700,
    top: 100,
    width: 100,
    height: 300,
  })
})
