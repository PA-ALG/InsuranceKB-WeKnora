// @vitest-environment happy-dom

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import {
  buildSchemaCitationPreviewPath,
  readPinnedSchemaCitationPreview,
} from '../../api/schema-wiki/index.ts'
import { parseSchemaWikiScope } from '../../views/knowledge/schema-wiki/schemaWikiContract.ts'
import SchemaCitationViewer from './SchemaCitationViewer.vue'
import { createPdfJsPort, type PdfJsApi } from './pdfJsPort.ts'
import type { CitationPinV1, CitationTargetV1 } from './schemaCitationTarget.ts'

const H = (character: string) => character.repeat(64)
const vector = JSON.parse(readFileSync(resolve(
  process.cwd(), '../internal/application/service/testdata/schema_wiki_contract_vector.json',
), 'utf8')) as {
  citations: Array<Record<string, unknown>>
  release: { citation_bindings: Array<Record<string, string>> }
}

function citation(pageNumber: number): CitationTargetV1 {
  return {
    ...structuredClone(vector.citations[0]),
    citation_id: `citation-page-${pageNumber}`,
    citation_sha256: H(pageNumber === 12 ? 'c' : 'd'),
    chunk_id: `chunk-page-${pageNumber}`,
    locator_ref: `block-page-${pageNumber}`,
    page_number: pageNumber,
    bbox: {
      coordinate_system: 'pdf_points',
      page_width: 1000,
      page_height: 1000,
      x0: 100,
      y0: 200,
      x1: 400,
      y1: 300,
    },
  } as CitationTargetV1
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
      citation_sha256: target.citation_sha256,
      logical_member_ref: target.logical_member_ref,
      member_digest: binding.member_digest,
      binding_sha256: H('b'),
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

function pdfPort(pageCount = 27) {
  return {
    open: vi.fn(async () => ({
      pageCount,
      renderPage: vi.fn(async (pageNumber: number) => ({
        pageNumber,
        width: 800,
        height: 1200,
        canvas: document.createElement('canvas'),
      })),
    })),
  }
}

describe('SchemaCitationViewer exact page and bbox rendering', () => {
  it.each([12, 27])('renders exact page %i with a visible bbox overlay', async pageNumber => {
    const target = citation(pageNumber)
    const port = pdfPort()
    const wrapper = mount(SchemaCitationViewer, {
      props: {
        target,
        pin: pin(target),
        previewBytes: new Uint8Array([0x25, 0x50, 0x44, 0x46]),
        pdfPort: port,
      },
    })

    await vi.waitFor(() => {
      expect(wrapper.get('[data-testid="citation-page"]').attributes('data-page-number')).toBe(String(pageNumber))
    })
    const highlight = wrapper.get('[data-testid="citation-highlight"]')
    expect(highlight.isVisible()).toBe(true)
    expect(highlight.attributes('style')).toContain('left: 80px')
    expect(highlight.attributes('style')).toContain('top: 240px')
  })

  it('does not open a PDF or manufacture page one when page authority is missing', async () => {
    const target = citation(12)
    const port = pdfPort()
    const { page_number: _page, ...missingPage } = target
    const wrapper = mount(SchemaCitationViewer, {
      props: {
        target: missingPage,
        pin: pin(target),
        previewBytes: new Uint8Array([0x25, 0x50, 0x44, 0x46]),
        pdfPort: port,
      },
    })

    await vi.waitFor(() => {
      expect(wrapper.get('[data-testid="citation-error"]').text()).toBe('PAGE_UNAVAILABLE')
    })
    expect(port.open).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="citation-page"]').exists()).toBe(false)
  })

  it('rejects an out-of-range exact page instead of rendering page one', async () => {
    const target = citation(12)
    const port = pdfPort(11)
    const wrapper = mount(SchemaCitationViewer, {
      props: {
        target,
        pin: pin(target),
        previewBytes: new Uint8Array([0x25, 0x50, 0x44, 0x46]),
        pdfPort: port,
      },
    })

    await vi.waitFor(() => {
      expect(wrapper.get('[data-testid="citation-error"]').text()).toBe('PAGE_UNAVAILABLE')
    })
    expect(wrapper.find('[data-testid="citation-highlight"]').exists()).toBe(false)
  })

  it('reports a missing bbox as unavailable without opening the PDF', async () => {
    const target = citation(12)
    const port = pdfPort()
    const { bbox: _bbox, ...missingBBox } = target
    const wrapper = mount(SchemaCitationViewer, {
      props: {
        target: missingBBox,
        pin: pin(target),
        previewBytes: new Uint8Array([0x25, 0x50, 0x44, 0x46]),
        pdfPort: port,
      },
    })

    await vi.waitFor(() => {
      expect(wrapper.get('[data-testid="citation-error"]').text()).toBe('BBOX_UNAVAILABLE')
    })
    expect(port.open).not.toHaveBeenCalled()
  })

  it('rejects revision/member custody drift before opening the PDF', async () => {
    const target = citation(12)
    const port = pdfPort()
    const wrapper = mount(SchemaCitationViewer, {
      props: {
        target,
        pin: { ...pin(target), source_revision_id: 'revision-foreign' },
        previewBytes: new Uint8Array([0x25, 0x50, 0x44, 0x46]),
        pdfPort: port,
      },
    })

    await vi.waitFor(() => {
      expect(wrapper.get('[data-testid="citation-error"]').text()).toBe('CITATION_REPLAY_IDENTITY_MISMATCH')
    })
    expect(port.open).not.toHaveBeenCalled()
  })
})

describe('pinned preview API and pdfjs adapter', () => {
  it('builds only the exact release/field/citation preview path and returns copied bytes', async () => {
    const scope = parseSchemaWikiScope({
      version: 'schema-wiki-scope.v1',
      space_id: 'space-a',
      raw_kb_id: 'raw-a',
      wiki_kb_id: 'wiki-a',
      scope_sha256: H('4'),
    })
    expect(buildSchemaCitationPreviewPath(scope, 'release-r1', 'field-a', 'citation-a')).toBe(
      '/api/v1/knowledgebase/wiki-a/wiki/release-scopes/space-a/raw/raw-a/schema/releases/release-r1/fields/field-a/citations/citation-a/preview',
    )
    const source = new Uint8Array([1, 2, 3])
    const transport = { getBytes: vi.fn(async () => source) }
    const actual = await readPinnedSchemaCitationPreview(
      scope, 'release-r1', 'field-a', 'citation-a', transport,
    )
    expect(transport.getBytes).toHaveBeenCalledOnce()
    expect(actual).toEqual(source)
    expect(actual).not.toBe(source)
  })

  it('opens bytes and renders the exact requested page through pdfjs', async () => {
    const render = vi.fn(async () => undefined)
    const getPage = vi.fn(async (pageNumber: number) => ({
      getViewport: () => ({ width: 600, height: 800 }),
      render: () => ({ promise: render() }),
    }))
    const getDocument = vi.fn(() => ({ promise: Promise.resolve({ numPages: 27, getPage }) }))
    const port = createPdfJsPort({ getDocument } as unknown as PdfJsApi)
    const opened = await port.open(new Uint8Array([1, 2, 3]))
    const page = await opened.renderPage(27)
    expect(getPage).toHaveBeenCalledWith(27)
    expect(page.pageNumber).toBe(27)
    expect(page.width).toBe(600)
    expect(page.height).toBe(800)
    expect(render).toHaveBeenCalledOnce()
  })
})
