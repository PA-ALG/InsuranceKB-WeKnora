// @vitest-environment happy-dom

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'

import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import {
  buildSchemaCitationPreviewPath,
  readPinnedSchemaCitationPreview,
} from '../../api/schema-wiki/index.ts'
import * as schemaWikiApi from '../../api/schema-wiki/index.ts'
import { parseSchemaWikiScope } from '../../views/knowledge/schema-wiki/schemaWikiContract.ts'
import SchemaCitationViewer from './SchemaCitationViewer.vue'
import type { CitationTargetV1 } from './schemaCitationTarget.ts'

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

const immutablePreviewApi = schemaWikiApi as unknown as {
  buildSchemaCitationPreviewRequest(input: ImmutableRevisionPreviewRequestV1): ImmutableRevisionPreviewRequestV1
  createSchemaWikiCitationPreviewTransport(
    scope: ReturnType<typeof parseSchemaWikiScope>,
    transport: {
      get(path: string): Promise<unknown>
      getBytes(path: string): Promise<Uint8Array>
    },
  ): {
    getAuthority(request: ImmutableRevisionPreviewRequestV1): Promise<unknown>
    getBytesByToken(token: string): Promise<Uint8Array>
  }
}
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

const previewBytes = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x37])
const previewFileSha256 = createHash('sha256').update(previewBytes).digest('hex')

function immutablePreviewRequest(
  sourceRole: 'terms' | 'brochure' | 'rate_table',
  pageNumber: number,
): ImmutableRevisionPreviewRequestV1 {
  return {
    release_id: 'release-r1',
    activation_epoch: 9,
    field_id: 'field-a',
    citation_id: `citation-${sourceRole}-${pageNumber}`,
  }
}

function immutablePreviewAuthority(
  sourceRole: 'terms' | 'brochure',
  pageNumber: number,
): ImmutableRevisionPreviewV1 {
  const request = immutablePreviewRequest(sourceRole, pageNumber)
  const target = citation(pageNumber)
  return {
    contract: 'schema-wiki-citation-content-authority.v1',
    token_key_id: 'citation-token-key-1',
    ...request,
    revision_source: {
      contract: 'live-revision-source-receipt.v1',
      revision_source_id: H(sourceRole === 'terms' ? '4' : '5'),
      tenant_id: 10003,
      space_id: target.space_id,
      raw_kb_id: 'raw-596-1',
      wiki_kb_id: 'wiki-596-1',
      knowledge_id: target.knowledge_id,
      evidence_parse_attempt_id: target.parse_attempt_id,
      weknora_parse_attempt: sourceRole === 'terms' ? 2 : 1,
      resource_id: `resource-${sourceRole}`,
      file_sha256: previewFileSha256,
      size: previewBytes.byteLength,
      mime_type: 'application/pdf',
      page_count: sourceRole === 'terms' ? 39 : 27,
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

describe('SchemaCitationViewer exact page and bbox rendering', () => {
  it('does not expose the former caller-supplied target, pin, or bytes props', () => {
    expect(Object.keys((SchemaCitationViewer as unknown as { props: Record<string, unknown> }).props ?? {}))
      .not.toEqual(expect.arrayContaining(['target', 'pin', 'previewBytes']))
  })
})

describe('pinned preview API', () => {
  it('rejects the legacy direct-byte path before transport', async () => {
    const scope = parseSchemaWikiScope({
      version: 'schema-wiki-scope.v1',
      space_id: 'space-a',
      raw_kb_id: 'raw-a',
      wiki_kb_id: 'wiki-a',
      scope_sha256: H('4'),
    })
    const getBytes = vi.fn(async () => previewBytes)

    await expect(readPinnedSchemaCitationPreview(
      scope,
      'release-r1',
      'field-a',
      'citation-a',
      { getBytes },
    )).rejects.toThrow('CITATION_PREVIEW_AUTHORITY_REQUIRED')
    expect(getBytes).not.toHaveBeenCalled()
  })

  it('builds only the exact release/field/citation authority path', () => {
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
  })

  it('routes authority by the Active tuple and bytes only by opaque token', async () => {
    const scope = parseSchemaWikiScope({
      version: 'schema-wiki-scope.v1',
      space_id: 'space-a',
      raw_kb_id: 'raw-a',
      wiki_kb_id: 'wiki-a',
      scope_sha256: H('4'),
    })
    const get = vi.fn(async () => ({ authority: true }))
    const getBytes = vi.fn(async () => previewBytes)
    const transport = immutablePreviewApi.createSchemaWikiCitationPreviewTransport(
      scope,
      { get, getBytes },
    )
    const request = immutablePreviewRequest('terms', 12)

    await transport.getAuthority(request)
    await transport.getBytesByToken('key-terms.payload-12.signature-terms')

    expect(get).toHaveBeenCalledWith(
      '/api/v1/knowledgebase/wiki-a/wiki/release-scopes/space-a/raw/raw-a/schema'
      + '/releases/release-r1/fields/field-a/citations/citation-terms-12/preview',
    )
    expect(getBytes).toHaveBeenCalledWith(
      '/api/v1/knowledgebase/wiki-a/wiki/release-scopes/space-a/raw/raw-a/schema'
      + '/citation-content/key-terms.payload-12.signature-terms',
    )
  })

})

describe('immutable revision citation preview', () => {
  it('submits only the Active release/epoch/field/citation tuple', () => {
    const request = immutablePreviewApi.buildSchemaCitationPreviewRequest(
      immutablePreviewRequest('terms', 12),
    )
    expect(Object.keys(request).sort()).toEqual([
      'activation_epoch', 'citation_id', 'field_id', 'release_id',
    ])
    expect(request).toEqual({
      release_id: 'release-r1',
      activation_epoch: 9,
      field_id: 'field-a',
      citation_id: 'citation-terms-12',
    })
    expect(JSON.stringify(request)).not.toMatch(/current|latest|material|presign|page/i)
  })

  it.each([
    ['terms', 12],
    ['brochure', 27],
  ] as const)('loads %s page %i by opaque token, verifies bytes, and renders the exact page', async (
    sourceRole,
    pageNumber,
  ) => {
    const request = immutablePreviewRequest(sourceRole, pageNumber)
    const authority = immutablePreviewAuthority(sourceRole, pageNumber)
    const transport = {
      getAuthority: vi.fn(async (actual: ImmutableRevisionPreviewRequestV1) => {
        expect(actual).toEqual(request)
        return authority
      }),
      getBytesByToken: vi.fn(async (token: string) => {
        expect(token).toBe(authority.opaque_token)
        return previewBytes
      }),
    }
    const port = pdfPort(authority.revision_source.page_count)
    const wrapper = mount(SchemaCitationViewer, {
      props: { request, previewTransport: transport, pdfPort: port } as never,
    })

    await vi.waitFor(() => {
      expect(wrapper.get('[data-testid="citation-page"]').attributes('data-page-number')).toBe(String(pageNumber))
    })
    expect(transport.getAuthority).toHaveBeenCalledOnce()
    expect(transport.getBytesByToken).toHaveBeenCalledOnce()
    expect(port.open).toHaveBeenCalledOnce()
  })

  it.each([12, 27])('keeps rate-table page %i unavailable with token, bytes, and PdfPort calls at zero', async pageNumber => {
    const request = immutablePreviewRequest('rate_table', pageNumber)
    const transport = {
      getAuthority: vi.fn(async () => { throw new Error('PAGE_UNAVAILABLE') }),
      getBytesByToken: vi.fn(),
    }
    const port = pdfPort(2)
    const wrapper = mount(SchemaCitationViewer, {
      props: { request, previewTransport: transport, pdfPort: port } as never,
    })

    await vi.waitFor(() => {
      expect(wrapper.get('[data-testid="citation-error"]').text()).toBe('PAGE_UNAVAILABLE')
    })
    expect(transport.getAuthority).toHaveBeenCalledOnce()
    expect(transport.getBytesByToken).not.toHaveBeenCalled()
    expect(port.open).not.toHaveBeenCalled()
  })

  it('rejects unavailable bbox before token bytes or PdfPort', async () => {
    const request = immutablePreviewRequest('terms', 12)
    const authority = immutablePreviewAuthority('terms', 12)
    const transport = {
      getAuthority: vi.fn(async () => ({
        ...authority,
        bbox: { ...authority.bbox, coordinate_system: 'unknown' },
      })),
      getBytesByToken: vi.fn(),
    }
    const port = pdfPort(authority.revision_source.page_count)
    const wrapper = mount(SchemaCitationViewer, {
      props: { request, previewTransport: transport, pdfPort: port } as never,
    })

    await vi.waitFor(() => {
      expect(wrapper.get('[data-testid="citation-error"]').text()).toBe('BBOX_UNAVAILABLE')
    })
    expect(transport.getAuthority).toHaveBeenCalledOnce()
    expect(transport.getBytesByToken).not.toHaveBeenCalled()
    expect(port.open).not.toHaveBeenCalled()
  })

  it('rejects byte hash drift after token fetch and before PdfPort', async () => {
    const request = immutablePreviewRequest('terms', 12)
    const authority = immutablePreviewAuthority('terms', 12)
    const transport = {
      getAuthority: vi.fn(async () => authority),
      getBytesByToken: vi.fn(async () => new Uint8Array([0x00])),
    }
    const port = pdfPort(authority.revision_source.page_count)
    const wrapper = mount(SchemaCitationViewer, {
      props: { request, previewTransport: transport, pdfPort: port } as never,
    })

    await vi.waitFor(() => {
      expect(wrapper.get('[data-testid="citation-error"]').text()).toBe('PREVIEW_BYTES_HASH_MISMATCH')
    })
    expect(transport.getBytesByToken).toHaveBeenCalledWith(authority.opaque_token)
    expect(port.open).not.toHaveBeenCalled()
  })

  it('returns from preview with the same Active release and epoch pin', async () => {
    const request = immutablePreviewRequest('terms', 12)
    const authority = immutablePreviewAuthority('terms', 12)
    const transport = {
      getAuthority: vi.fn(async () => authority),
      getBytesByToken: vi.fn(async () => previewBytes),
    }
    const wrapper = mount(SchemaCitationViewer, {
      props: {
        request,
        previewTransport: transport,
        pdfPort: pdfPort(authority.revision_source.page_count),
      } as never,
    })
    await vi.waitFor(() => wrapper.get('[data-testid="citation-page"]'))
    await wrapper.get('[data-testid="citation-back"]').trigger('click')
    expect(wrapper.emitted('back')).toEqual([[
      { release_id: request.release_id, activation_epoch: request.activation_epoch },
    ]])
  })
})
