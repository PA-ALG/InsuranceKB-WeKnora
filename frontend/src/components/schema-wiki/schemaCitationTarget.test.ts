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

const H = (character: string) => character.repeat(64)
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
