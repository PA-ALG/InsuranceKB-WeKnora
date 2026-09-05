import { readFileSync } from 'node:fs'
import { describe, expect, it, vi } from 'vitest'
import { readConceptPage830G2, conceptCitationTransport830G2 } from './conceptFreeWiki830G2'

const vector = JSON.parse(readFileSync(new URL(
  '../../../../harness/tests/fixtures/concept_free_wiki_830_g2_contract_vector.json', import.meta.url,
), 'utf8'))
const scope = { version: 'schema-wiki-scope.v1', space_id: 'space-a', raw_kb_id: 'raw-a',
  wiki_kb_id: 'wiki-a', scope_sha256: 'a'.repeat(64) }
function fixture() {
  return { success: true, data: {
    contract: 'concept-page-read.830.g2.v1', read_mode: 'pinned', release_id: 'release-a',
    activation_epoch: 4, candidate_hash: vector.candidate_hash,
    space_id: 'space-a', raw_kb_id: 'raw-a', wiki_kb_id: 'wiki-a',
    member: structuredClone(vector.page_manifest.members[0]), related_members: [],
    citations: [{ citation_id: `citation-${'b'.repeat(24)}`, page_number: 1, quote: '被保险人' }],
    definition_hash: 'c'.repeat(64), aggregate_hash: 'd'.repeat(64),
  } }
}

it.each(['group-extra', 'group-missing', 'group-owner', 'field-extra', 'field-missing', 'empty-evidence'])(
  'rejects incomplete or foreign navigation: %s', async kind => {
    const response = fixture()
    if (kind.startsWith('group-')) {
      response.data.member = structuredClone(vector.page_manifest.members.find((m: {kind:string}) => m.kind === 'entity_overview'))
      response.data.related_members = structuredClone(vector.page_manifest.members.filter((m: {member_id:string}) => response.data.member.payload.member_ids.includes(m.member_id)))
      if (kind === 'group-extra') response.data.related_members.push(structuredClone(vector.page_manifest.members[0]) as never)
      if (kind === 'group-missing') response.data.related_members.pop()
      if (kind === 'group-owner') response.data.member.owner_id = 'foreign-entity'
    } else if (kind.startsWith('field-')) {
      response.data.member = structuredClone(vector.page_manifest.members.find((m: {kind:string,payload:{concept_ids?:string[]}}) => m.kind === 'field_assertion' && m.payload.concept_ids?.length))
      if (kind === 'field-extra') response.data.related_members = [structuredClone(vector.page_manifest.members.find((m: {kind:string}) => m.kind === 'free_wiki'))] as never[]
    } else response.data.member.payload.evidence = []
    const get = vi.fn().mockResolvedValueOnce({success:true,data:scope}).mockResolvedValue(response)
    await expect(readConceptPage830G2('wiki-a',response.data.member.member_id,'release-a',{get})).rejects.toThrow()
    expect(get).toHaveBeenCalledTimes(2)
  })

it.each(['entity_overview', 'free_wiki', 'field_assertion', 'free_wiki_item'])(
  'renders the complete frozen navigation for %s', async kind => {
    const response = fixture()
    response.data.member = structuredClone(vector.page_manifest.members.find((m: {kind:string}) => m.kind === kind))
    const links = response.data.member.payload.member_ids ?? response.data.member.payload.concept_ids
    response.data.related_members = structuredClone(vector.page_manifest.members.filter((m: {member_id:string}) => links.includes(m.member_id)))
    const get = vi.fn().mockResolvedValueOnce({success:true,data:scope}).mockResolvedValue(response)
    const session = await readConceptPage830G2('wiki-a',response.data.member.member_id,'release-a',{get})
    expect(session.read.related_members.map(m => m.member_id).sort()).toEqual([...links].sort())
  })

describe('G2 release-bound page client', () => {
  it('reads a member from the requested release through the existing scoped route', async () => {
    const response = fixture()
    const get = vi.fn().mockResolvedValueOnce({ success: true, data: scope }).mockResolvedValue(response)
    const result = await readConceptPage830G2('wiki-a', response.data.member.member_id, 'release-a', { get })
    expect(result.read.member.content).toContain('保险合同')
    expect(get.mock.calls[1][0]).toContain(`/concept-pages/${response.data.member.member_id}?release_id=release-a`)
  })
  it.each(['release', 'scope', 'member', 'mode'])('rejects %s drift without a fallback read', async kind => {
    const response = fixture()
    const expected = response.data.member.member_id
    if (kind === 'release') response.data.release_id = 'release-b'
    if (kind === 'scope') response.data.space_id = 'foreign'
    if (kind === 'member') response.data.member = { ...response.data.member, member_id: 'other' }
    if (kind === 'mode') response.data.read_mode = 'current'
    const get = vi.fn().mockResolvedValueOnce({ success: true, data: scope }).mockResolvedValue(response)
    await expect(readConceptPage830G2('wiki-a', expected, 'release-a', { get })).rejects.toThrow()
    expect(get).toHaveBeenCalledTimes(2)
  })
  it('rejects moving release aliases before making requests', async () => {
    const get = vi.fn()
    await expect(readConceptPage830G2('wiki-a', 'concept-id', 'current', { get })).rejects.toThrow()
    expect(get).not.toHaveBeenCalled()
  })
  it('binds citation requests to the loaded member and release', async () => {
    const response = fixture()
    const io = { get: vi.fn().mockResolvedValueOnce({ success: true, data: scope }).mockResolvedValue(response),
      getBytes: vi.fn().mockResolvedValue(new Uint8Array([1, 2])) }
    const session = await readConceptPage830G2('wiki-a', response.data.member.member_id, 'release-a', io)
    const transport = conceptCitationTransport830G2(session, io)
    await expect(transport.getAuthority({ release_id: 'release-b', activation_epoch: 4,
      field_id: response.data.member.member_id, citation_id: response.data.citations[0].citation_id })).rejects.toThrow()
    expect(io.get).toHaveBeenCalledTimes(2)
    await transport.getAuthority({ release_id: 'release-a', activation_epoch: 4,
      field_id: response.data.member.member_id, citation_id: response.data.citations[0].citation_id })
    expect(io.get.mock.calls[2][0]).toContain('/preview?release_id=release-a')
  })
})


it.each(['concept-owner','field-owner','unrelated-field','evidence-space','evidence-kb'])(
  'rejects the frozen member relationship drift: %s', async kind => {
    const response = fixture()
    if (kind === 'concept-owner') response.data.member.owner_id = 'foreign-space'
    if (kind.startsWith('evidence-')) {
      const evidence = response.data.member.payload.evidence[0]
      if (kind === 'evidence-space') evidence.space_id = 'foreign-space'
      else evidence.raw_kb_id = 'foreign-kb'
    }
    if (kind === 'field-owner' || kind === 'unrelated-field') {
      const field = structuredClone(vector.page_manifest.members.find((m: {kind:string})=>m.kind==='field_assertion'))
      if (kind === 'field-owner') field.owner_id = 'entity-b'
      else field.payload.concept_ids = []
      response.data.related_members = [field] as never[]
    }
    const get = vi.fn().mockResolvedValueOnce({success:true,data:scope}).mockResolvedValue(response)
    await expect(readConceptPage830G2('wiki-a',response.data.member.member_id,'release-a',{get})).rejects.toThrow()
    expect(get).toHaveBeenCalledTimes(2)
  })
