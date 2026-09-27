// @vitest-environment happy-dom
import { createHash, webcrypto } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { parseConceptCitationAuthority830G2 } from './conceptCitationAuthority830G2'
import ConceptCitationViewer from './ConceptCitationViewer830G2.vue'
import type { ConceptSession830G2 } from '@/api/schema-wiki/conceptFreeWiki830G2'

const H = (s: string) => createHash('sha256').update(s).digest('hex')
const bytes = new TextEncoder().encode('%PDF-test-exact-bytes')
const source = { tenant_id: 10003, space_id: 'space', raw_kb_id: 'raw', knowledge_id: 'knowledge',
  parse_attempt: 2, revision_id: H('revision'), source_hash: H('%PDF-test-exact-bytes'),
  parse_hash: H('parse'), parser_identity: H('parser') }
const evidence = { ...source, source_type: 'document', block_id: 'chunk', page_number: 1,
  offset_unit: 'UNICODE_CODE_POINT', start: 2, end: 5, quote: '被😀人', quote_hash: H('被😀人') }
const candidate = H('candidate')
const citation = 'citation-' + H(JSON.stringify([candidate, 'concept-a', source.revision_id,
  'chunk', 1, 2, 5, evidence.quote_hash])).slice(0, 24)
const session = { scope: { version: 'schema-wiki-scope.v1', space_id: 'space', raw_kb_id: 'raw',
  wiki_kb_id: 'wiki', scope_sha256: H('scope') }, read: { contract: 'concept-page-read.830.g2.v1',
  read_mode: 'pinned', release_id: 'release-a', activation_epoch: 4, candidate_hash: candidate,
  space_id: 'space', raw_kb_id: 'raw', wiki_kb_id: 'wiki', definition_hash: '', aggregate_hash: '',
  member: { kind: 'concept', member_id: 'concept-a', owner_id: 'space', title: '被保险人',
    content: '定义', payload: { evidence: [evidence] } }, related_members: [],
  citations: [{ citation_id: citation, page_number: 1, quote: evidence.quote }] } } as ConceptSession830G2
function canonical(v: any): string {
  if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']'
  if (v !== null && typeof v === 'object') return '{' + Object.keys(v).sort()
    .map(k => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}'
  return JSON.stringify(v)
}
function authority() {
  const unsigned = { contract: 'concept-citation-content-authority.830.g2.v1', token_key_id: 'g2-read',
    release_id: 'release-a', activation_epoch: 4, candidate_hash: candidate, member_id: 'concept-a',
    citation_id: citation, scope: { tenant_id: 10003, space_id: 'space', raw_kb_id: 'raw', wiki_kb_id: 'wiki' },
    source: { ...source }, revision_source: { binding_digest: H('binding'), file_sha256: source.source_hash,
      page_count: 39 }, block_id: 'chunk', page_number: 1, quote_hash: evidence.quote_hash,
    bbox: { coordinate_space: 'normalized_0_1e6_top_left', x0: 100000, y0: 200000, x1: 400000, y1: 300000 },
    expires_at_unix: Math.floor(Date.now() / 1000) + 120 }
  return { ...unsigned, authority_digest: H(unsigned.contract + '\n' + canonical(unsigned)), opaque_token: 'opaque.test-token' }
}
function blockAuthority() {
  const original = authority()
  const { authority_digest: _digest, opaque_token, ...base } = original
  const unsigned = { ...base, contract: 'concept-citation-content-authority.830.g3.v1',
    source_locator: { contract: 'concept-source-block-locator.830.g3.v1',
      source_block_sha256: H('完整来源块'), source_page_number: 1, start: 2, end: 5,
      block_global_start: 100, global_start: 102, global_end: 105, actual_page_number: 22 } }
  return { ...unsigned, authority_digest: H(unsigned.contract + '\n' + canonical(unsigned)), opaque_token }
}
beforeAll(() => vi.stubGlobal('crypto', webcrypto))
describe('G2 source authority and exact PDF viewer', () => {
  it('consumes the persisted Go authority vector without rebuilding its digest', async () => {
    const vector = JSON.parse(readFileSync(resolve(process.cwd(),
      '../internal/application/service/testdata/concept_source_authority_830_g2_vector.json'), 'utf8'))
    const a = vector.authority
    const replay = structuredClone(session)
    replay.scope = { ...replay.scope, ...vector.session.scope }
    replay.read = { ...replay.read, ...vector.session,
      member: { ...replay.read.member, member_id: a.member_id, payload: { evidence: [vector.evidence] } },
      citations: [{ citation_id: a.citation_id, page_number: a.page_number, quote: vector.evidence.quote }] }
    const clock = vi.spyOn(Date, 'now').mockReturnValue(vector.clock_unix * 1000)
    try {
      const accepted = await parseConceptCitationAuthority830G2({ ...a, opaque_token: 'test-only.token' }, replay, a.citation_id)
      expect(accepted.block_id).toBe('chunk-1')
      expect(a.authority_digest).toBe(vector.authority_digest)
    } finally { clock.mockRestore() }
  })
  it('accepts a closed authority tied to the exact non-BMP evidence and signed digest', async () => {
    expect((await parseConceptCitationAuthority830G2(authority(), session, citation)).block_id).toBe('chunk')
  })
  it.each(['release', 'scope', 'source', 'quote', 'bbox', 'expired', 'extra', 'digest'])('rejects %s drift before reading bytes', async kind => {
    const a: any = authority()
    if (kind === 'release') a.release_id = 'release-b'
    if (kind === 'scope') a.scope.raw_kb_id = 'another-raw'
    if (kind === 'source') a.source.revision_id = H('different')
    if (kind === 'quote') a.quote_hash = H('different')
    if (kind === 'bbox') a.bbox.x1 = a.bbox.x0
    if (kind === 'expired') a.expires_at_unix = 1
    if (kind === 'extra') a.source.untrusted = 'ignored?'
    if (kind === 'digest') a.authority_digest = H('different')
    else {
      const { authority_digest: _digest, opaque_token: _token, ...unsigned } = a
      a.authority_digest = H(a.contract + '\n' + canonical(unsigned))
    }
    await expect(parseConceptCitationAuthority830G2(a, session, citation)).rejects.toThrow()
  })
  it('renders exact pinned bytes and projects normalized coordinates', async () => {
    const canvas = document.createElement('canvas')
    const open = vi.fn().mockResolvedValue({ pageCount: 39,
      renderPage: vi.fn().mockResolvedValue({ pageNumber: 1, width: 600, height: 800, canvas }) })
    const getBytesByToken = vi.fn().mockResolvedValue(bytes)
    const wrapper = mount(ConceptCitationViewer, { props: { session, citationId: citation,
      previewTransport: { getAuthority: vi.fn().mockResolvedValue(authority()), getBytesByToken }, pdfPort: { open } } })
    await vi.waitFor(() => expect(wrapper.find('[data-testid="citation-page"]').exists()).toBe(true))
    expect(getBytesByToken).toHaveBeenCalledWith('opaque.test-token')
    expect(wrapper.get('[data-testid="citation-highlight"]').attributes('style')).toContain('left: 60px')
    expect(wrapper.get('[data-testid="citation-highlight"]').attributes('style')).toContain('top: 160px')
  })
  it('rejects changed PDF bytes before the PDF parser is called', async () => {
    const open = vi.fn()
    const wrapper = mount(ConceptCitationViewer, { props: { session, citationId: citation,
      previewTransport: { getAuthority: vi.fn().mockResolvedValue(authority()),
        getBytesByToken: vi.fn().mockResolvedValue(new TextEncoder().encode('wrong file')) }, pdfPort: { open } } })
    await vi.waitFor(() => expect(wrapper.find('[data-testid="citation-error"]').exists()).toBe(true))
    expect(open).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('PREVIEW_BYTES_HASH_MISMATCH')
    await flushPromises()
  })
  it('binds G3 physical location to the original Unicode evidence without rewriting its page', async () => {
    const a = await parseConceptCitationAuthority830G2(blockAuthority(), session, citation)
    expect(a.page_number).toBe(1)
    expect((a as any).source_locator.actual_page_number).toBe(22)
    expect(session.read.citations[0].page_number).toBe(1)
  })
  it('consumes the persisted Go G3 location vector with its unchanged digest', async () => {
    const vector = JSON.parse(readFileSync(resolve(process.cwd(),
      '../internal/application/service/testdata/concept_source_authority_830_g3_vector.json'), 'utf8'))
    const clock = vi.spyOn(Date, 'now').mockReturnValue(vector.clock_unix * 1000)
    try {
      const a = await parseConceptCitationAuthority830G2({ ...vector.authority,
        opaque_token: 'test-only.not-a-issued-token' }, vector.session, vector.authority.citation_id)
      expect(a.page_number).toBe(11)
      expect(a.source_locator?.actual_page_number).toBe(12)
      expect(vector.authority.authority_digest).toBe(vector.authority_digest)
      expect(vector.token_issued).toBe(false)
      expect(vector.private_key_reads).toBe(0)
    } finally { clock.mockRestore() }
  })
  it.each(['source-page', 'start', 'global-start', 'global-end', 'physical-page', 'block-hash',
    'extra', 'missing', 'g2-with-locator'])('rejects G3 locator %s drift even with a recomputed digest', async kind => {
    const a: any = blockAuthority()
    if (kind === 'source-page') a.source_locator.source_page_number = 2
    if (kind === 'start') {
      a.source_locator.start = 1; a.source_locator.end = 4
      a.source_locator.global_start = 101; a.source_locator.global_end = 104
    }
    if (kind === 'global-start') a.source_locator.global_start = 101
    if (kind === 'global-end') a.source_locator.global_end = 106
    if (kind === 'physical-page') a.source_locator.actual_page_number = 40
    if (kind === 'block-hash') a.source_locator.source_block_sha256 = 'unverified'
    if (kind === 'extra') a.source_locator.ignore = true
    if (kind === 'missing') delete a.source_locator
    if (kind === 'g2-with-locator') a.contract = 'concept-citation-content-authority.830.g2.v1'
    const { authority_digest: _digest, opaque_token: _token, ...unsigned } = a
    a.authority_digest = H(a.contract + '\n' + canonical(unsigned))
    await expect(parseConceptCitationAuthority830G2(a, session, citation)).rejects.toThrow()
  })
  it('renders the verified physical page for a G3 cross-page source block', async () => {
    const renderPage = vi.fn().mockResolvedValue({ pageNumber: 22, width: 600, height: 800,
      canvas: document.createElement('canvas') })
    const wrapper = mount(ConceptCitationViewer, { props: { session, citationId: citation,
      previewTransport: { getAuthority: vi.fn().mockResolvedValue(blockAuthority()),
        getBytesByToken: vi.fn().mockResolvedValue(bytes) },
      pdfPort: { open: vi.fn().mockResolvedValue({ pageCount: 39, renderPage }) } } })
    await vi.waitFor(() => expect(wrapper.find('[data-testid="citation-page"]').exists()).toBe(true))
    expect(renderPage).toHaveBeenCalledWith(22)
    expect(wrapper.get('[data-testid="citation-page"]').attributes('data-page-number')).toBe('22')
    expect(wrapper.text()).toContain('第 22 页')
  })
})

describe('citation viewer reuses only documents behind fresh authority', () => {
  it('checks authority twice but downloads and opens the same source once', async () => {
    const { createVerifiedPdfReuse } = await import('./verifiedPdfReuse')
    const close = vi.fn()
    const renderPage = vi.fn().mockImplementation(async () => ({ pageNumber: 1, width: 600, height: 800,
      canvas: document.createElement('canvas') }))
    const open = vi.fn().mockResolvedValue({ pageCount: 39, renderPage, close })
    const pdfPort = { open }; const pdfReuse = createVerifiedPdfReuse(pdfPort)
    const getAuthority = vi.fn().mockImplementation(async () => authority())
    const getBytesByToken = vi.fn().mockResolvedValue(bytes)
    const props = { session, citationId: citation, pdfPort, pdfReuse, previewTransport: { getAuthority, getBytesByToken } }
    const first = mount(ConceptCitationViewer, { props })
    await vi.waitFor(() => expect(first.find('[data-testid="citation-page"]').exists()).toBe(true))
    first.unmount()
    const second = mount(ConceptCitationViewer, { props })
    await vi.waitFor(() => expect(second.find('[data-testid="citation-page"]').exists()).toBe(true))
    expect(getAuthority).toHaveBeenCalledTimes(2)
    expect(getBytesByToken).toHaveBeenCalledTimes(1); expect(open).toHaveBeenCalledTimes(1)
    expect(renderPage).toHaveBeenCalledTimes(2)
    second.unmount(); pdfReuse.clear(); expect(close).toHaveBeenCalledTimes(1)
  })
  it('does not display a cached PDF when a fresh authority request fails', async () => {
    const { createVerifiedPdfReuse } = await import('./verifiedPdfReuse')
    const close = vi.fn()
    const open = vi.fn().mockResolvedValue({ pageCount: 39, close,
      renderPage: vi.fn().mockResolvedValue({ pageNumber: 1, width: 600, height: 800, canvas: document.createElement('canvas') }) })
    const pdfPort = { open }; const pdfReuse = createVerifiedPdfReuse(pdfPort)
    const getAuthority = vi.fn().mockResolvedValueOnce(authority()).mockRejectedValueOnce(new Error('source revoked'))
    const props = { session, citationId: citation, pdfPort, pdfReuse,
      previewTransport: { getAuthority, getBytesByToken: vi.fn().mockResolvedValue(bytes) } }
    const first = mount(ConceptCitationViewer, { props })
    await vi.waitFor(() => expect(first.find('[data-testid="citation-page"]').exists()).toBe(true)); first.unmount()
    const second = mount(ConceptCitationViewer, { props })
    await vi.waitFor(() => expect(second.find('[data-testid="citation-error"]').exists()).toBe(true))
    expect(second.find('[data-testid="citation-page"]').exists()).toBe(false)
    expect(close).toHaveBeenCalledTimes(1); expect(open).toHaveBeenCalledTimes(1)
    second.unmount(); pdfReuse.clear()
  })
})
