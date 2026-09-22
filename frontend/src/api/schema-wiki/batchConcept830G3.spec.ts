import { readFileSync } from 'node:fs'

import { describe, expect, it, vi } from 'vitest'

import { parseSchemaPackCatalog830G3 } from './schemaPackCatalog830G3'
import {
  loadBatchConceptActive830G3,
  readPinnedBatchConceptPage830G3,
  loadBatchConceptPreparation830G3,
  parseBatchConceptActive830G3,
  parseBatchConceptPreparation830G3,
  readBatchConceptPage830G3,
} from './batchConcept830G3'
import { parseSchemaWikiScope } from '../../views/knowledge/schema-wiki/schemaWikiContract'

const candidate = JSON.parse(readFileSync(new URL(
  '../../../../harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json', import.meta.url,
), 'utf8')) as Record<string, any>
const encoder = new TextEncoder()

function canonical(value: unknown): string {
  if (value === null || typeof value === 'boolean' || typeof value === 'string' || typeof value === 'number') {
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  const record = value as Record<string, unknown>
  return `{${Object.keys(record).sort().map(key => `${JSON.stringify(key)}:${canonical(record[key])}`).join(',')}}`
}
async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', encoder.encode(value))
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('')
}
async function domainHash(contract: string, value: unknown): Promise<string> {
  return sha256(`schema-wiki-canonical.v1\u0000${contract}\u0000${canonical(value)}`)
}

const base = candidate.request.base_request
const scopeValue = {
  version: 'schema-wiki-scope.v1', space_id: base.space_id, raw_kb_id: base.raw_kb_id,
  wiki_kb_id: base.wiki_kb_id, scope_sha256: '7'.repeat(64),
}
const scope = parseSchemaWikiScope(scopeValue)

async function catalog() {
  return parseSchemaPackCatalog830G3(structuredClone(candidate.request.catalog))
}

async function preparationResponse(mutator?: (value: Record<string, any>) => void) {
  const value: Record<string, any> = {
    contract: 'batch-concept-preparation-read.830.g3.v1', read_mode: 'preparation',
    tenant_id: base.tenant_id, space_id: base.space_id, raw_kb_id: base.raw_kb_id,
    wiki_kb_id: base.wiki_kb_id, preparation_id: 'preparation-g3', status: 'DRAFT',
    candidate_sha256: candidate.candidate_hash, expected_base_release_id: base.base_release_id,
    expected_base_activation_epoch: base.base_activation_epoch,
    page_manifest: structuredClone(candidate.page_manifest), read_sha256: '',
  }
  mutator?.(value)
  value.read_sha256 = await domainHash(value.contract, Object.fromEntries(
    Object.entries(value).filter(([key]) => key !== 'read_sha256'),
  ))
  return value
}

async function refreshManifestHashes(response: Record<string, any>) {
  response.page_manifest.members_sha256 = await domainHash('batch-concept-page-members.830.g3.v1', {
    members: response.page_manifest.members,
  })
  response.read_sha256 = await domainHash(response.contract, Object.fromEntries(
    Object.entries(response).filter(([key]) => key !== 'read_sha256'),
  ))
}

async function snapshots() {
  return Promise.all(candidate.page_manifest.members.map(async (member: Record<string, any>) => ({
    kind: member.kind, logical_slug: member.member_id, revision_id: candidate.candidate_hash,
    member_digest: await domainHash('batch-concept-member.830.g3.v1', member),
    title: member.title, content: member.content, payload: member.payload,
  })))
}

describe('G3 batch concept preparation parser', () => {
  it('parses the exact frozen 354-member/342-field preparation and derives Profile navigation', async () => {
    const result = await parseBatchConceptPreparation830G3(
      await preparationResponse(), scope, await catalog(), 'preparation-g3',
    )
    expect(result.mode).toBe('g3-preparation')
    expect(result.statusLabel).toBe('待审核')
    expect(result.candidateHash).toBe(candidate.candidate_hash)
    expect(result.members).toHaveLength(354)
    expect(result.entities).toHaveLength(5)
    expect(result.entities.reduce((total, entity) => total + entity.fieldCount, 0)).toBe(342)
    expect(result.entities.filter(entity => entity.schemaPackID === 'schemapack_medical_insurance'))
      .toEqual([expect.objectContaining({ fieldCount: 67 }), expect.objectContaining({ fieldCount: 67 })])
    expect(result.entities.flatMap(entity => entity.sections).flatMap(section => section.fields)
      .some(field => field.fieldKey === 'social_insurance_requirement')).toBe(false)
  })

  it('moves navigation while preserving schema, fields and evidence', async () => {
    const original = await preparationResponse()
    const response = structuredClone(original)
    const overview = response.page_manifest.members.find((m: any) => m.kind === 'entity_overview')
    const assignment: Record<string, any> = {
      contract: 'g3-navigation-assignment.830.v1', entity_id: overview.owner_id,
      entity_version: overview.payload.entity_version, assignment_version: 1,
      labels: [overview.payload.primary_classification, '健康保障'].sort(), primary_label: '健康保障',
      previous_assignment_sha256: 'a'.repeat(64),
    }
    assignment.assignment_sha256 = await domainHash(assignment.contract, assignment)
    overview.payload.navigation_assignment = assignment
    await refreshManifestHashes(response)
    const parsed = await parseBatchConceptPreparation830G3(response, scope, await catalog(), 'preparation-g3')
    const entity = parsed.entities.find(item => item.entityID === overview.owner_id)!
    expect(entity.navigationPrimaryLabel).toBe('健康保障')
    expect(entity.primaryClassification).toBe(overview.payload.primary_classification)
    expect(entity.schemaPackSHA256).toBe(overview.payload.schema_pack_sha256)
    expect(parsed.members.filter(item => item.kind === 'field_assertion')).toEqual(
      original.page_manifest.members.filter((item: any) => item.kind === 'field_assertion'))
    const unicode = structuredClone(response)
    const unicodeAssignment = unicode.page_manifest.members.find((m: any) => m.member_id === overview.member_id)
      .payload.navigation_assignment
    unicodeAssignment.labels = ['\ue000', '😀']
    unicodeAssignment.primary_label = '😀'
    unicodeAssignment.assignment_sha256 = await domainHash(unicodeAssignment.contract, Object.fromEntries(
      Object.entries(unicodeAssignment).filter(([key]) => key !== 'assignment_sha256')))
    await refreshManifestHashes(unicode)
    expect((await parseBatchConceptPreparation830G3(unicode, scope, await catalog(), 'preparation-g3'))
      .entities.find(item => item.entityID === overview.owner_id)?.navigationPrimaryLabel).toBe('😀')
    for (const patch of [
      { entity_id: 'foreign-entity' }, { assignment_version: 0 },
      { labels: ['健康保障', '健康保障'] }, { primary_label: 'unlisted' },
      { assignment_sha256: '0'.repeat(64) }, { labels: ['x'.repeat(81)], primary_label: 'x'.repeat(81) },
    ]) {
      const bad = structuredClone(response)
      Object.assign(bad.page_manifest.members.find((m: any) => m.member_id === overview.member_id)
        .payload.navigation_assignment, patch)
      await refreshManifestHashes(bad)
      await expect(parseBatchConceptPreparation830G3(bad, scope, await catalog(), 'preparation-g3')).rejects.toThrow()
    }
  })

  it('rejects omitted, null, extra, non-NFC, duplicate and fully rehashed topology drift', async () => {
    const cases: Record<string, any>[] = []
    const omitted = await preparationResponse(); delete omitted.status; cases.push(omitted)
    cases.push(await preparationResponse(value => { value.status = null }))
    cases.push(await preparationResponse(value => { value.extra = true }))
    const nestedOmitted = await preparationResponse()
    delete nestedOmitted.page_manifest.members.find((m: any) => m.kind === 'field_assertion').payload.conditions
    await refreshManifestHashes(nestedOmitted); cases.push(nestedOmitted)
    const nestedNull = await preparationResponse()
    nestedNull.page_manifest.members.find((m: any) => m.kind === 'field_assertion').payload.conditions = null
    await refreshManifestHashes(nestedNull); cases.push(nestedNull)
    const nonNFC = await preparationResponse()
    nonNFC.page_manifest.members.find((m: any) => m.kind === 'field_assertion').title = 'e\u0301'
    await refreshManifestHashes(nonNFC); cases.push(nonNFC)
    const duplicate = await preparationResponse()
    duplicate.page_manifest.members.push(structuredClone(duplicate.page_manifest.members[0]))
    await refreshManifestHashes(duplicate); cases.push(duplicate)
    const profileDrift = await preparationResponse()
    profileDrift.page_manifest.members.find((m: any) => m.kind === 'entity_overview').payload.sections[0].fields.pop()
    await refreshManifestHashes(profileDrift); cases.push(profileDrift)
    const versionDrift = await preparationResponse()
    const driftField = versionDrift.page_manifest.members.find((m: any) => m.kind === 'field_assertion')
    driftField.payload.entity_version = `${driftField.owner_id}@different`
    await refreshManifestHashes(versionDrift); cases.push(versionDrift)
    const orphanFreeItem = await preparationResponse()
    orphanFreeItem.page_manifest.members.find((m: any) => m.kind === 'free_wiki' && m.payload.member_ids.length)
      .payload.member_ids = []
    await refreshManifestHashes(orphanFreeItem); cases.push(orphanFreeItem)
    for (const value of cases) {
      await expect(parseBatchConceptPreparation830G3(value, scope, await catalog(), 'preparation-g3'))
        .rejects.toThrow('BATCH_CONCEPT_830_G3_INVALID')
    }
  }, 15_000)

  it('rejects scope, identity and read-hash drift and maps READY distinctly', async () => {
    const ready = await preparationResponse(value => { value.status = 'READY' })
    expect((await parseBatchConceptPreparation830G3(ready, scope, await catalog(), 'preparation-g3')).statusLabel)
      .toBe('已审核但未发布')
    for (const mutate of [
      (v: any) => { v.space_id = 'foreign' },
      (v: any) => { v.preparation_id = 'other' },
      (v: any) => { v.read_sha256 = '0'.repeat(64) },
    ]) {
      const value = await preparationResponse(); mutate(value)
      await expect(parseBatchConceptPreparation830G3(value, scope, await catalog(), 'preparation-g3'))
        .rejects.toThrow('BATCH_CONCEPT_830_G3_INVALID')
    }
  })

  it('rejects ASCII controls in structured text while preserving exact typed multiline bodies', async () => {
    for (const control of ['\u0000', '\t', '\n', '\r', '\u001f', '\u007f']) {
      const sourceIdentity = await preparationResponse()
      sourceIdentity.page_manifest.members.find((m: any) => m.kind === 'field_assertion' && m.payload.evidence.length)
        .payload.evidence[0].parser_identity = `parser${control}identity`
      await refreshManifestHashes(sourceIdentity)
      await expect(parseBatchConceptPreparation830G3(sourceIdentity, scope, await catalog(), 'preparation-g3'))
        .rejects.toThrow('BATCH_CONCEPT_830_G3_INVALID')
    }
    const structuredArray = await preparationResponse()
    structuredArray.page_manifest.members.find((m: any) => m.kind === 'concept').payload.aliases = ['alias\tname']
    await refreshManifestHashes(structuredArray)
    await expect(parseBatchConceptPreparation830G3(structuredArray, scope, await catalog(), 'preparation-g3'))
      .rejects.toThrow('BATCH_CONCEPT_830_G3_INVALID')

    const displayName = await preparationResponse()
    const overview = displayName.page_manifest.members.find((m: any) => m.kind === 'entity_overview')
    overview.payload.display_name += '\nname'; overview.title = overview.payload.display_name
    await refreshManifestHashes(displayName)
    await expect(parseBatchConceptPreparation830G3(displayName, scope, await catalog(), 'preparation-g3'))
      .rejects.toThrow('BATCH_CONCEPT_830_G3_INVALID')

    const profileLabel = await preparationResponse()
    const profileCatalog: any = structuredClone(await catalog())
    const profileOverview = profileLabel.page_manifest.members.find((m: any) => m.kind === 'entity_overview')
    profileOverview.payload.sections[0].display_name += '\rlabel'
    profileCatalog.entries.find((entry: any) => entry.pack.schema_pack_id === profileOverview.payload.schema_pack_id)
      .profile.sections[0].display_name = profileOverview.payload.sections[0].display_name
    await refreshManifestHashes(profileLabel)
    await expect(parseBatchConceptPreparation830G3(profileLabel, scope, profileCatalog, 'preparation-g3'))
      .rejects.toThrow('BATCH_CONCEPT_830_G3_INVALID')

    const multiline = await preparationResponse()
    const unknown = multiline.page_manifest.members.find((m: any) =>
      m.kind === 'field_assertion' && m.payload.state === 'unknown')
    unknown.payload.unknown_reason = '待\t核\n实\r原文'
    unknown.payload.conditions = ['条件\t一']; unknown.payload.exceptions = ['例外\n一']; unknown.payload.valid_time = '长期\r有效'
    unknown.content = '未知：待\t核\n实\r原文\n条件：条件\t一\n例外：例外\n一\n有效期：长期\r有效'
    const known = multiline.page_manifest.members.find((m: any) =>
      m.kind === 'field_assertion' && m.payload.evidence.length)
    known.payload.evidence[0].quote = '原\t文\n证\r据'
    known.payload.evidence[0].end = known.payload.evidence[0].start + Array.from(known.payload.evidence[0].quote).length
    known.payload.evidence[0].quote_hash = await sha256(known.payload.evidence[0].quote)
    const concept = multiline.page_manifest.members.find((m: any) => m.kind === 'concept')
    concept.payload.title = concept.title = '被\t保险人'; concept.payload.body = concept.content = '定义\n正文\r保留'
    const free = multiline.page_manifest.members.find((m: any) => m.kind === 'free_wiki_item')
    free.payload.title = free.title = '案例\t标题'; free.payload.body = '案例\r\n正文'
    free.payload.conditions = ['条件\t二']; free.payload.exceptions = ['例外\n二']; free.payload.valid_time = '期间\r二'
    free.content = '案例\r\n正文\n条件：条件\t二\n例外：例外\n二\n有效期：期间\r二'
    multiline.page_manifest.audit[0].reason = '审核\t原因\n保留\r原文'
    const crlf = structuredClone(multiline)
    const crlfUnknown = crlf.page_manifest.members.find((m: any) => m.member_id === unknown.member_id)
    crlfUnknown.payload.unknown_reason = crlfUnknown.payload.unknown_reason.replace('核\n实', '核\r\n实')
    crlfUnknown.content = crlfUnknown.content.replace('核\n实', '核\r\n实')
    await refreshManifestHashes(multiline)
    await refreshManifestHashes(crlf)
    expect(crlf.page_manifest.members_sha256).not.toBe(multiline.page_manifest.members_sha256)
    expect(crlf.read_sha256).not.toBe(multiline.read_sha256)
    const parsed = await parseBatchConceptPreparation830G3(multiline, scope, await catalog(), 'preparation-g3')
    const crlfParsed = await parseBatchConceptPreparation830G3(crlf, scope, await catalog(), 'preparation-g3')
    expect(parsed.members.find(member => member.member_id === unknown.member_id)?.payload.unknown_reason)
      .toBe('待\t核\n实\r原文')
    expect(parsed.members.find(member => member.member_id === known.member_id)?.payload.evidence)
      .toEqual(expect.arrayContaining([expect.objectContaining({ quote: '原\t文\n证\r据' })]))
    expect(parsed.members.find(member => member.member_id === free.member_id)?.content).toBe(free.content)
    expect(crlfParsed.members.find(member => member.member_id === unknown.member_id)?.payload.unknown_reason)
      .toBe('待\t核\r\n实\r原文')
  }, 30_000)
})

describe('G3 batch concept Active parser and mocked transports', () => {
  it('parses exact Active snapshots without casting the G3 overview to G2', async () => {
    const result = await parseBatchConceptActive830G3(await snapshots(), scope, await catalog(), {
      release_id: 'release-g3', activation_epoch: 6,
    })
    expect(result.mode).toBe('g3-active')
    expect(result.releaseID).toBe('release-g3')
    expect(result.candidateHash).toBe(candidate.candidate_hash)
    expect(result.entities).toHaveLength(5)
  })

  it('accepts published search order without changing the snapshots or relaxing member hashes', async () => {
    const rows = (await snapshots()).sort((left, right) => left.logical_slug < right.logical_slug ? -1 : left.logical_slug > right.logical_slug ? 1 : 0)
    const original = structuredClone(rows)
    const result = await parseBatchConceptActive830G3(rows, scope, await catalog(), {
      release_id: 'release-g3', activation_epoch: 6,
    })
    expect(result.entities).toHaveLength(5)
    expect(rows).toEqual(original)
    expect(result.members.map(member => `${member.kind}\u0000${member.member_id}`)).toEqual(
      result.members.map(member => `${member.kind}\u0000${member.member_id}`).sort(),
    )
    rows[0].member_digest = '0'.repeat(64)
    await expect(parseBatchConceptActive830G3(rows, scope, await catalog(), {
      release_id: 'release-g3', activation_epoch: 6,
    })).rejects.toThrow('BATCH_CONCEPT_830_G3_INVALID')
  })

  it('uses preparation scope and immutable GET without current, and permits only the exact historical q-empty read', async () => {
    const response = await preparationResponse()
    const rows = [{ kind: 'field_assertion', logical_slug: 'assertion_old', revision_id: '8'.repeat(64),
      member_digest: '9'.repeat(64), title: 'social_insurance_requirement', content: '未知：FIXTURE_NO_MODEL_FACT',
      payload: { space_id: scope.space_id, entity_id: 'old', field_key: 'social_insurance_requirement', state: 'unknown',
        value: null, attempted: true, unknown_reason: 'FIXTURE_NO_MODEL_FACT', evidence: [], concept_ids: [], conditions: [],
        exceptions: [], entity_version: 'old@v', valid_time: '' } }]
    const get = vi.fn(async (path: string) => {
      if (path.includes('/wiki/preparations/preparation-g3/schema-scope')) return { success: true, data: scopeValue }
      if (path.includes('/catalogs/')) return { success: true, data: candidate.request.catalog }
      if (path.endsWith('/schema/preparations/preparation-g3/batch-concept')) return { success: true, data: response }
      if (path.endsWith(`/releases/${base.base_release_id}/search?q=`)) return { success: true, data: rows }
      throw new Error(`unexpected ${path}`)
    })
    await expect(loadBatchConceptPreparation830G3(scope.wiki_kb_id, 'preparation-g3', { get }))
      .rejects.toThrow('BATCH_CONCEPT_830_G3_ALIGNMENT_INVALID')
    const paths = get.mock.calls.map(call => call[0])
    expect(paths.some(path => path.endsWith('/current'))).toBe(false)
    expect(paths.filter(path => path.includes('/search')).every(path => path.endsWith('?q='))).toBe(true)
  })

  it('pins Active current then exact search', async () => {
    const current = { release_id: 'release-g3', activation_epoch: 6 }
    const activeRows = await snapshots()
    const get = vi.fn(async (path: string) => {
      if (path.endsWith('/wiki/schema-scope')) return { success: true, data: scopeValue }
      if (path.includes('/catalogs/')) return { success: true, data: candidate.request.catalog }
      if (path.endsWith('/current')) return { success: true, data: current }
      if (path.endsWith('/search?q=')) return { success: true, data: activeRows }
      throw new Error(`unexpected ${path}`)
    })
    const result = await loadBatchConceptActive830G3(scope.wiki_kb_id, { get })
    expect(result?.releaseID).toBe('release-g3')
    const paths = get.mock.calls.map(call => call[0])
    expect(paths.findIndex(path => /\/current$/.test(path))).toBeLessThan(
      paths.findIndex(path => /\/releases\/release-g3\/search\?q=$/.test(path)),
    )
  })

  it('leaves an ordinary G2 current release independent of the G3 Catalog', async () => {
    const get = vi.fn(async (path: string) => {
      if (path.endsWith('/wiki/schema-scope')) return { success: true, data: scopeValue }
      if (path.endsWith('/current')) return { success: true, data: { release_id: 'release-g2', activation_epoch: 5 } }
      if (path.endsWith('/search?q=')) return { success: true, data: [{ payload: { member_ids: [] } }] }
      if (path.includes('/catalogs/')) throw new Error('G3 Catalog must not gate G2')
      throw new Error(`unexpected ${path}`)
    })
    await expect(loadBatchConceptActive830G3(scope.wiki_kb_id, { get })).resolves.toBeNull()
    expect(get.mock.calls.flat().some(path => String(path).includes('/catalogs/'))).toBe(false)
  })

  it('reads a historical G3 page once using its authenticated epoch and immutable snapshot', async () => {
    const rows = await snapshots()
    const active = await parseBatchConceptActive830G3(rows, scope, await catalog(), {
      release_id: 'release-old', activation_epoch: 4,
    })
    const overview = active.entities[0]!.overview
    const ids = new Set(active.entities[0]!.sections.flatMap(section => section.fields.map(field => field.memberID)))
    const page = { contract: 'concept-page-read.830.g2.v1', read_mode: 'pinned', release_id: 'release-old',
      activation_epoch: 4, candidate_hash: candidate.candidate_hash, space_id: scope.space_id,
      raw_kb_id: scope.raw_kb_id, wiki_kb_id: scope.wiki_kb_id, member: overview,
      related_members: active.members.filter(member => ids.has(member.member_id)), citations: [], definition_hash: '', aggregate_hash: '' }
    const get = vi.fn(async (path: string) => {
      if (path.endsWith('/wiki/schema-scope')) return { success: true, data: scopeValue }
      if (path.endsWith('/releases/release-old/search?q=')) return { success: true, data: rows }
      if (path.includes('/catalogs/')) return { success: true, data: candidate.request.catalog }
      if (path.endsWith(`/concept-pages/${overview.member_id}?release_id=release-old`)) return { success: true, data: page }
      throw new Error(`unexpected ${path}`)
    })
    const result = await readPinnedBatchConceptPage830G3(scope.wiki_kb_id, overview.member_id, 'release-old', { get })
    expect(result?.directory).toMatchObject({ releaseID: 'release-old', activationEpoch: 4 })
    expect(result?.member).toEqual(overview)
    expect(get.mock.calls.filter(([path]) => path.includes('/concept-pages/'))).toHaveLength(1)
    expect(get.mock.calls.some(([path]) => path.endsWith('/current'))).toBe(false)
    page.activation_epoch = 0
    await expect(readPinnedBatchConceptPage830G3(scope.wiki_kb_id, overview.member_id, 'release-old', { get })).rejects.toThrow()
    page.activation_epoch = 4; page.release_id = 'release-new'
    await expect(readPinnedBatchConceptPage830G3(scope.wiki_kb_id, overview.member_id, 'release-old', { get })).rejects.toThrow()
    page.release_id = 'release-old'; page.raw_kb_id = 'other-raw'
    await expect(readPinnedBatchConceptPage830G3(scope.wiki_kb_id, overview.member_id, 'release-old', { get })).rejects.toThrow()
    page.raw_kb_id = scope.raw_kb_id; rows[0]!.member_digest = '0'.repeat(64)
    await expect(readPinnedBatchConceptPage830G3(scope.wiki_kb_id, overview.member_id, 'release-old', { get })).rejects.toThrow()
  })

  it('leaves historical G2 pages to their original reader without loading a G3 Catalog or page', async () => {
    const get = vi.fn(async (path: string) => {
      if (path.endsWith('/wiki/schema-scope')) return { success: true, data: scopeValue }
      if (path.endsWith('/releases/release-g2/search?q=')) return { success: true, data: [{ payload: { member_ids: [] } }] }
      throw new Error(`unexpected ${path}`)
    })
    await expect(readPinnedBatchConceptPage830G3(scope.wiki_kb_id, 'concept-g2', 'release-g2', { get })).resolves.toBeNull()
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('selects preparation members locally and reads Active pages through the pinned shared envelope', async () => {
    const prepared = await parseBatchConceptPreparation830G3(
      await preparationResponse(), scope, await catalog(), 'preparation-g3',
    )
    const field = prepared.members.find(member => member.kind === 'field_assertion')!
    const localGet = vi.fn()
    const local = await readBatchConceptPage830G3(prepared, field.member_id, { get: localGet })
    expect(local.readMode).toBe('preparation')
    expect(local.member).toBe(field)
    expect(localGet).not.toHaveBeenCalled()
    const get = vi.fn(async () => ({ success: true, data: {
      contract: 'concept-page-read.830.g2.v1', read_mode: 'pinned', release_id: 'release-g3',
      activation_epoch: 6, candidate_hash: candidate.candidate_hash, space_id: scope.space_id,
      raw_kb_id: scope.raw_kb_id, wiki_kb_id: scope.wiki_kb_id,
      member: field, related_members: [], citations: [], definition_hash: '', aggregate_hash: '',
    } }))
    const active = await parseBatchConceptActive830G3(await snapshots(), scope, await catalog(), {
      release_id: 'release-g3', activation_epoch: 6,
    })
    expect((await readBatchConceptPage830G3(active, field.member_id, { get })).readMode).toBe('active')
    expect(get).toHaveBeenCalledWith(expect.stringMatching(/concept-pages\/.+\?release_id=release-g3$/))
  })

  it('accepts overview related members only in frozen manifest order', async () => {
    const active = await parseBatchConceptActive830G3(await snapshots(), scope, await catalog(), {
      release_id: 'release-g3', activation_epoch: 6,
    })
    const overview = active.members.find(member => member.kind === 'entity_overview')!
    const referenced = new Set((overview.payload.sections as Record<string, any>[])
      .flatMap(section => section.fields.map((field: Record<string, any>) => field.member_id)))
    const related = active.members.filter(member => referenced.has(member.member_id))
    expect(related.map(member => member.member_id)).not.toEqual(
      [...referenced],
    )
    const get = vi.fn(async () => ({ success: true, data: {
      contract: 'concept-page-read.830.g2.v1', read_mode: 'pinned', release_id: 'release-g3',
      activation_epoch: 6, candidate_hash: candidate.candidate_hash, space_id: scope.space_id,
      raw_kb_id: scope.raw_kb_id, wiki_kb_id: scope.wiki_kb_id,
      member: overview, related_members: related, citations: [], definition_hash: '', aggregate_hash: '',
    } }))
    await expect(readBatchConceptPage830G3(active, overview.member_id, { get })).resolves.toMatchObject({
      relatedMembers: related,
    })
  })
})
