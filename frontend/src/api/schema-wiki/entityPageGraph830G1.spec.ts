import { readFileSync } from 'node:fs'

import { describe, expect, it, vi } from 'vitest'

import { parseSchemaWikiScope } from '../../views/knowledge/schema-wiki/schemaWikiContract.ts'
import { parseEntityPageGraphRead830G1 } from '../../views/knowledge/schema-wiki/entityPageGraph830G1Contract.ts'
import {
  buildEntityPageGraphPath830G1,
  createEntityPageGraphPreparationCitationTransport830G1,
  readEntityPageGraph830G1,
  readEntityPageGraphSession830G1,
} from './entityPageGraph830G1.ts'

const scope = parseSchemaWikiScope({
  version: 'schema-wiki-scope.v1',
  space_id: 'space-1',
  raw_kb_id: 'raw-1',
  wiki_kb_id: 'wiki-1',
  scope_sha256: 'a'.repeat(64),
})

interface EntityPageGraphVector830G1 {
  release_id: string
  activation_epoch: number
  manifest_sha256: string
  space_id: string
  wiki_kb_id: string
  entity_id: string
  entity_version_id: string
  display_name: string
  classification_display_name: string
  profile: unknown
  members: Array<{ stable_key: string, short_title: string, [key: string]: unknown }>
}

const vector = JSON.parse(readFileSync(new URL(
  '../../../../harness/tests/fixtures/entity_page_graph_830_g1_contract_vector.json',
  import.meta.url,
), 'utf8')) as EntityPageGraphVector830G1

const successorReleaseID = 'release-g1-successor'

function responseFor(stableKey: string) {
  const fixtureMember = vector.members.find(item => item.stable_key === stableKey)
  if (!fixtureMember) throw new Error(`missing fixture member: ${stableKey}`)
  const member = structuredClone(fixtureMember)
  return {
    success: true,
    data: {
      contract: 'entity-page-read.830.g1.v1',
      read_mode: 'current',
      release_id: successorReleaseID,
      activation_epoch: vector.activation_epoch + 1,
      manifest_sha256: vector.manifest_sha256,
      entity_id: vector.entity_id,
      entity_version_id: vector.entity_version_id,
      display_name: vector.display_name,
      classification_display_name: vector.classification_display_name,
      profile: vector.profile,
      member,
    },
  }
}

function firstCitationBBox(response: ReturnType<typeof responseFor>): Record<string, unknown> {
  const payload = response.data.member.payload
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
    throw new Error('fixture field payload missing')
  }
  const citations = (payload as Record<string, unknown>).citations
  if (!Array.isArray(citations) || citations.length === 0) throw new Error('fixture citation missing')
  const citation = citations[0]
  if (typeof citation !== 'object' || citation === null || Array.isArray(citation)) {
    throw new Error('fixture citation invalid')
  }
  const bbox = (citation as Record<string, unknown>).bbox
  if (typeof bbox !== 'object' || bbox === null || Array.isArray(bbox)) {
    throw new Error('fixture bbox missing')
  }
  return bbox as Record<string, unknown>
}

describe('entity page graph 830 G1 API', () => {
  it('accepts the frozen profile-driven 7/67 field wire and retains short title plus namespace', () => {
    const read = parseEntityPageGraphRead830G1(responseFor('insured_eligibility'), {
      entityId: vector.entity_id, pageKind: 'field', stableKey: 'insured_eligibility',
    })
    expect(read.profile.sections).toHaveLength(7)
    expect(read.profile.sections.flatMap(section => section.fields)).toHaveLength(67)
    expect(read.member.short_title).toBe('投保范围')
    expect(read.member.namespace).toContain(':field:insured_eligibility')
    expect(read.member.payload.contract).toBe('field-assertion-page.830.g1.v1')
  })

  it('rejects presentation drift before rendering', () => {
    const response = responseFor('cooling_off_period')
    response.data.member.short_title = '漂移标题'
    expect(() => parseEntityPageGraphRead830G1(response, {
      entityId: vector.entity_id, pageKind: 'field', stableKey: 'cooling_off_period',
    })).toThrow('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
  })

  it.each([
    ['coordinate system', 'coordinate_system', 'pdf_points'],
    ['fixed width', 'page_width', 999_999],
    ['fixed height', 'page_height', 999_999],
    ['integer coordinate', 'x0', 100_000.5],
    ['ordered x coordinates', 'x0', 1_000_000],
    ['ordered y coordinates', 'y1', 200_000],
    ['nonnegative coordinates', 'x0', -1],
    ['bounded coordinates', 'x1', 1_000_001],
  ])('rejects citation bbox with invalid %s', (_name, key, value) => {
    const response = responseFor('insured_eligibility')
    firstCitationBBox(response)[key] = value
    expect(() => parseEntityPageGraphRead830G1(response, {
      entityId: vector.entity_id, pageKind: 'field', stableKey: 'insured_eligibility',
    })).toThrow('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
  })

  it('builds the four stable semantic paths and preserves an exact pinned release', () => {
    expect(buildEntityPageGraphPath830G1(scope, {
      entityId: 'entity-1', pageKind: 'overview', stableKey: 'overview',
    })).toBe('/api/v1/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/schema/entities/entity-1/overview')
    expect(buildEntityPageGraphPath830G1(scope, {
      entityId: 'entity-1', pageKind: 'section', stableKey: 'section-1',
    }, 'release-exact')).toContain('/sections/section-1?release_id=release-exact')
    expect(buildEntityPageGraphPath830G1(scope, {
      entityId: 'entity-1', pageKind: 'field', stableKey: 'field-1',
    })).toContain('/fields/field-1')
    expect(buildEntityPageGraphPath830G1(scope, {
      entityId: 'entity-1', pageKind: 'free_wiki', stableKey: 'free-wiki',
    })).toContain('/free-wiki')
  })

  it('does not retry or fall back when the exact pinned read fails', async () => {
    const get = vi.fn()
      .mockResolvedValueOnce(scope)
      .mockRejectedValueOnce(new Error('ENTITY_PAGE_GRAPH_NOT_FOUND'))

    await expect(readEntityPageGraph830G1(
      'wiki-1',
      { entityId: 'entity-1', pageKind: 'field', stableKey: 'field-1' },
      'release-exact',
      { get },
    )).rejects.toThrow('ENTITY_PAGE_GRAPH_NOT_FOUND')
    expect(get).toHaveBeenCalledTimes(2)
    expect(get.mock.calls[1][0]).toContain('?release_id=release-exact')
  })

  it('returns the validated bootstrap scope that was used for the entity read', async () => {
    const actualScope = {
      version: 'schema-wiki-scope.v1',
      space_id: vector.space_id,
      raw_kb_id: 'raw-596-1',
      wiki_kb_id: vector.wiki_kb_id,
      scope_sha256: '4'.repeat(64),
    }
    const get = vi.fn()
      .mockResolvedValueOnce({ success: true, data: actualScope })
      .mockResolvedValueOnce(responseFor('insured_eligibility'))

    const session = await readEntityPageGraphSession830G1(
      vector.wiki_kb_id,
      { entityId: vector.entity_id, pageKind: 'field', stableKey: 'insured_eligibility' },
      undefined,
      { get },
    )

    expect(session.scope).toEqual(actualScope)
    expect(session.read.member.space_id).toBe(session.scope.space_id)
    expect(session.read.member.wiki_kb_id).toBe(session.scope.wiki_kb_id)
    expect(get.mock.calls).toEqual([
      [`/api/v1/knowledgebase/${vector.wiki_kb_id}/wiki/schema-scope`],
      [expect.stringContaining(
        `/release-scopes/${vector.space_id}/raw/${actualScope.raw_kb_id}/schema/entities/`,
      )],
    ])
  })

  it.each(['', ' ', ' current', 'current', 'latest'])('rejects the invalid explicit pin %j before transport', async releaseId => {
    const get = vi.fn()
    await expect(readEntityPageGraph830G1(
      'wiki-1',
      { entityId: 'entity-1', pageKind: 'overview', stableKey: 'overview' },
      releaseId,
      { get },
    )).rejects.toThrow('ENTITY_PAGE_GRAPH_RELEASE_ID_INVALID')
    expect(get).not.toHaveBeenCalled()
  })

  it('bootstraps one exact preparation scope and preserves Candidate Preview mode', async () => {
    const response = responseFor('insured_eligibility')
    response.data.read_mode = 'preparation'
    response.data.release_id = vector.release_id
    response.data.activation_epoch = vector.activation_epoch
    const preparationRead = response.data as typeof response.data & { preparation_id: string }
    preparationRead.preparation_id = 'preparation-g1'
    const actualScope = {
      version: 'schema-wiki-scope.v1', space_id: vector.space_id, raw_kb_id: 'raw-596-1',
      wiki_kb_id: vector.wiki_kb_id, scope_sha256: '4'.repeat(64),
    }
    const get = vi.fn()
      .mockResolvedValueOnce({ success: true, data: actualScope })
      .mockResolvedValueOnce(response)

    const session = await readEntityPageGraphSession830G1(
      vector.wiki_kb_id,
      { entityId: vector.entity_id, pageKind: 'field', stableKey: 'insured_eligibility' },
      undefined,
      { get },
      'preparation-g1',
    )

    expect(session.read.read_mode).toBe('preparation')
    expect(session.read.preparation_id).toBe('preparation-g1')
    expect(get.mock.calls).toEqual([
      [`/api/v1/knowledgebase/${vector.wiki_kb_id}/wiki/preparations/preparation-g1/schema-scope`],
      [expect.stringContaining('?preparation_id=preparation-g1')],
    ])
  })

  it('rejects mixed or aliased preparation mode before transport', async () => {
    const get = vi.fn()
    await expect(readEntityPageGraphSession830G1(
      'wiki-1',
      { entityId: 'entity-1', pageKind: 'overview', stableKey: 'overview' },
      'release-1',
      { get },
      'preparation-1',
    )).rejects.toThrow('ENTITY_PAGE_GRAPH_READ_MODE_INVALID')
    await expect(readEntityPageGraphSession830G1(
      'wiki-1',
      { entityId: 'entity-1', pageKind: 'overview', stableKey: 'overview' },
      undefined,
      { get },
      'latest',
    )).rejects.toThrow('ENTITY_PAGE_GRAPH_PREPARATION_ID_INVALID')
    expect(get).not.toHaveBeenCalled()
  })

  it('uses the full G1 citation identity for preparation authority and the old token content path', async () => {
    const fullCitationID = `citation_${'3'.repeat(64)}`
    const get = vi.fn().mockResolvedValue({ authority: true })
    const getBytes = vi.fn().mockResolvedValue(new Uint8Array([1, 2, 3]))
    const transport = createEntityPageGraphPreparationCitationTransport830G1(
      scope, 'preparation-g1', 'entity-1', fullCitationID, { get, getBytes },
    )
    await transport.getAuthority({
      release_id: 'release-source', activation_epoch: 2, field_id: 'field-1',
      citation_id: `citation-${'3'.repeat(24)}`,
    })
    expect(get).toHaveBeenCalledWith(
      expect.stringContaining(`/preparations/preparation-g1/entities/entity-1/fields/field-1/citations/${fullCitationID}/preview`),
    )
    await expect(transport.getBytesByToken('opaque-token')).resolves.toEqual(new Uint8Array([1, 2, 3]))
    expect(getBytes).toHaveBeenCalledWith(expect.stringContaining('/schema/citation-content/opaque-token'))
  })
})
