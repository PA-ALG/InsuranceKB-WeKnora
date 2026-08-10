import assert from 'node:assert/strict'
import test from 'node:test'

import {
  assertPinnedCitation,
  citationHighlightStyle,
  parseCitationTarget,
} from './schemaCitationTarget.ts'

const H = (character: string) => character.repeat(64)

function target(pageNumber: number) {
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
    chunk_id: `chunk-page-${pageNumber}`,
    page_number: pageNumber,
    locator_kind: 'block',
    locator_id: `block-page-${pageNumber}`,
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

function pin() {
  return {
    release_id: 'release-r1',
    field_id: 'product_name',
    logical_member_ref: 'fields/product_name',
    member_digest: H('b'),
    citation_binding: {
      citation_sha256: H('c'),
      member_digest: H('b'),
    },
    source_revision_id: 'knowledge-terms:attempt-2',
    parse_attempt: 2,
    document_sha256: H('d'),
    manifest_sha256: H('e'),
  }
}

test('page 12 and page 27 remain distinct exact targets', () => {
  assert.equal(parseCitationTarget(target(12)).page_number, 12)
  assert.equal(parseCitationTarget(target(27)).page_number, 27)
})

test('knowledge-only or current/latest references are not formal citations', () => {
  assert.throws(() => parseCitationTarget({
    knowledge_id: 'knowledge-terms',
    title: 'terms.pdf',
  }), { message: 'CITATION_TARGET_INCOMPLETE' })
  assert.throws(() => parseCitationTarget({
    ...target(12),
    source_revision_id: 'current',
  }), { message: 'CITATION_REVISION_NOT_PINNED' })
  assert.throws(() => parseCitationTarget({
    ...target(12),
    source_revision_id: 'latest',
  }), { message: 'CITATION_REVISION_NOT_PINNED' })
  assert.throws(() => parseCitationTarget({
    ...target(12),
    source_revision_id: 'CURRENT',
  }), { message: 'CITATION_REVISION_NOT_PINNED' })
  assert.throws(() => parseCitationTarget({
    ...target(12),
    locator_id: 'block-12\u0000foreign',
  }), { message: 'CITATION_TARGET_INCOMPLETE' })
})

test('missing or zero page is PAGE_UNAVAILABLE and never defaults to page one', () => {
  const { page_number: _page, ...missingPage } = target(12)
  assert.throws(() => parseCitationTarget(missingPage), { message: 'PAGE_UNAVAILABLE' })
  assert.throws(() => parseCitationTarget({ ...target(12), page_number: 0 }), {
    message: 'PAGE_UNAVAILABLE',
  })
})

test('invalid, degenerate, or fabricated full-page bbox is rejected', () => {
  assert.throws(() => parseCitationTarget({
    ...target(12),
    bbox: { x0: 300, y0: 200, x1: 300, y1: 400, coordinate_space: 'normalized_0_1000' },
  }), { message: 'BBOX_UNAVAILABLE' })
  assert.throws(() => parseCitationTarget({
    ...target(12),
    bbox: { x0: 0, y0: 0, x1: 1000, y1: 1000, coordinate_space: 'normalized_0_1000' },
  }), { message: 'BBOX_UNAVAILABLE' })
  assert.throws(() => parseCitationTarget({
    ...target(12),
    bbox: { x0: 1, y0: 2, x1: 3, y1: 4, coordinate_space: 'unknown' },
  }), { message: 'BBOX_UNAVAILABLE' })
})

test('release member, citation binding, revision, and manifest drift fail before preview', () => {
  const exactTarget = parseCitationTarget(target(12))
  assert.doesNotThrow(() => assertPinnedCitation(exactTarget, pin()))
  assert.throws(() => assertPinnedCitation(exactTarget, {
    ...pin(),
    member_digest: H('9'),
  }), { message: 'CITATION_MEMBER_BINDING_MISMATCH' })
  assert.throws(() => assertPinnedCitation({ ...exactTarget, manifest_sha256: H('9') }, pin()), {
    message: 'CITATION_REPLAY_IDENTITY_MISMATCH',
  })
})

test('normalized bbox transforms to a visible viewport overlay without page fallback', () => {
  assert.deepEqual(citationHighlightStyle(parseCitationTarget(target(12)), {
    width: 800,
    height: 1200,
  }), {
    left: 80,
    top: 240,
    width: 240,
    height: 120,
  })
})
