import { readFileSync } from 'node:fs'

import { describe, expect, it, vi } from 'vitest'

import { loadConceptDirectory830G2, parseConceptCatalog830G2 } from './conceptDirectory830G2'

const H = (n: number) => n.toString(16).padStart(64, '0')
const scope = { version: 'schema-wiki-scope.v1' as const, space_id: 'space-a', raw_kb_id: 'raw-a',
  wiki_kb_id: 'wiki-serving', scope_sha256: H(1) }
const current = { release_id: 'release-a', activation_epoch: 4 }
const evidence = { tenant_id: 1, space_id: 'space-a', raw_kb_id: 'raw-a', knowledge_id: 'knowledge-a',
  parse_attempt: 1, revision_id: 'revision-a', source_hash: H(2), parse_hash: H(3),
  parser_identity: H(4), source_type: 'DOCUMENT', block_id: 'block-a', page_number: 1,
  offset_unit: 'UNICODE_CODE_POINT', start: 0, end: 3, quote: '被保险', quote_hash: H(5) }

function snapshot(kind: string, logical_slug: string, title: string, content: string,
  payload: Record<string, unknown>, i: number) {
  return { kind, logical_slug, revision_id: H(99), member_digest: H(100 + i), title, content, payload }
}

function a70() {
  const conceptID = `concept_${H(10)}`
  const concept = snapshot('concept', conceptID, '被保险人', '共享定义', {
    space_id: 'space-a', canonical_key: 'insured-person', sense_key: 'insurance', title: '被保险人',
    body: '共享定义', evidence: [evidence], aliases: [], origin: 'MODEL_COMPILE',
  }, 0)
  const fields = Array.from({ length: 67 }, (_, i) => {
    const known = i < 2
    const fieldKey = `field-${i.toString().padStart(2, '0')}`
    return snapshot('field_assertion', `assertion_${H(200 + i)}`, fieldKey,
      known ? `真实值${i}` : '未知：本次编译未形成断言', {
        space_id: 'space-a', entity_id: 'entity-a', field_key: fieldKey,
        state: known ? 'present' : 'unknown', value: known ? `真实值${i}` : null,
        attempted: true, unknown_reason: known ? null : '本次编译未形成断言',
        evidence: known ? [evidence] : [], concept_ids: known ? [conceptID] : [],
        conditions: [], exceptions: [], entity_version: '596-1', valid_time: '',
      }, i + 1)
  })
  const memberIDs = fields.map(item => item.logical_slug).sort()
  return [concept,
    snapshot('entity_overview', `entity_overview_${H(20)}`, 'entity-a', '', { member_ids: memberIDs }, 68),
    ...fields,
    snapshot('free_wiki', `free_wiki_${H(21)}`, '开放知识', '', { member_ids: [] }, 69),
  ].sort((a, b) => a.kind.localeCompare(b.kind) || a.logical_slug.localeCompare(b.logical_slug))
}

function pageMember(row: ReturnType<typeof a70>[number], owner: string) {
  return { kind: row.kind, member_id: row.logical_slug, owner_id: owner,
    title: row.title, content: row.content, payload: row.payload }
}

function g2Transport(rows: ReturnType<typeof a70>, mutate?: (memberID: string, read: any) => void) {
  return vi.fn(async (path: string) => {
    if (path.endsWith('/wiki/schema-scope')) return { success: true, data: scope }
    if (path.endsWith('/current')) return { success: true, data: current }
    if (path.endsWith('/search?q=')) return { success: true, data: rows }
    const match = path.match(/\/concept-pages\/([^?]+)\?release_id=release-a$/)
    if (!match) throw new Error(`unexpected path: ${path}`)
    const memberID = decodeURIComponent(match[1])
    const row = rows.find(item => item.logical_slug === memberID)!
    const refs = (row.payload.member_ids as string[])
    let owner = row.kind === 'entity_overview' ? row.title : ''
    if (row.kind === 'free_wiki') {
      const referenced = rows.find(item => refs.includes(item.logical_slug))
      const rootIndex = rows.filter(item => item.kind === 'free_wiki')
        .sort((a, b) => a.logical_slug.localeCompare(b.logical_slug)).findIndex(item => item.logical_slug === memberID)
      const overview = rows.filter(item => item.kind === 'entity_overview')
        .sort((a, b) => a.logical_slug.localeCompare(b.logical_slug))[rootIndex]
      owner = referenced ? String(referenced.payload.entity_id) : overview.title
    }
    const related = refs.map(ref => {
      const found = rows.find(item => item.logical_slug === ref)!
      return pageMember(found, String(found.payload.entity_id))
    })
    const read: any = { contract: 'concept-page-read.830.g2.v1', read_mode: 'pinned', release_id: 'release-a',
      activation_epoch: 4, candidate_hash: H(99), space_id: 'space-a', raw_kb_id: 'raw-a',
      wiki_kb_id: 'wiki-serving', member: pageMember(row, owner), related_members: related,
      citations: [], definition_hash: '', aggregate_hash: '' }
    mutate?.(memberID, read)
    return { success: true, data: read }
  })
}

describe('G2 catalog contract', () => {
  it('loads the complete A 70-member release through scope, current and exact search', async () => {
    const get = g2Transport(a70())
    const result = await loadConceptDirectory830G2('wiki-serving', { get })
    expect(result.mode).toBe('g2')
    if (result.mode !== 'g2') throw new Error('expected G2')
    expect(result.members).toHaveLength(70)
    expect(result.concepts).toHaveLength(1)
    expect(result.entities).toEqual([expect.objectContaining({ entityID: 'entity-a', fieldCount: 67 })])
    expect(get.mock.calls.map(call => call[0]).slice(0, 3)).toEqual([
      '/api/v1/knowledgebase/wiki-serving/wiki/schema-scope',
      '/api/v1/knowledgebase/wiki-serving/wiki/release-scopes/space-a/raw/raw-a/current',
      '/api/v1/knowledgebase/wiki-serving/wiki/release-scopes/space-a/raw/raw-a/releases/release-a/search?q=',
    ])
    expect(get).toHaveBeenCalledTimes(5)
  })

  it('represents two entities with exact overview and free-wiki roots', async () => {
    const rows = a70()
    const firstField = rows.find(row => row.kind === 'field_assertion')!
    const secondField = structuredClone(firstField)
    secondField.logical_slug = `assertion_${H(500)}`
    secondField.member_digest = H(501)
    ;(secondField.payload as Record<string, unknown>).entity_id = 'entity-b'
    ;(secondField.payload as Record<string, unknown>).entity_version = '594-1'
    const rows2 = [...rows, secondField,
      snapshot('entity_overview', `entity_overview_${H(502)}`, 'entity-b', '',
        { member_ids: [secondField.logical_slug] }, 502),
      snapshot('free_wiki', `free_wiki_${H(503)}`, '开放知识', '', { member_ids: [] }, 503),
    ].sort((a, b) => a.kind.localeCompare(b.kind) || a.logical_slug.localeCompare(b.logical_slug))
    const get = g2Transport(rows2)
    const result = await loadConceptDirectory830G2('wiki-serving', { get })
    expect(result.mode).toBe('g2')
    if (result.mode === 'g2') {
      expect(result.entities.map(entity => entity.entityID)).toEqual(['entity-a', 'entity-b'])
      expect(result.entities.map(entity => entity.freeWiki.owner_id)).toEqual(['entity-a', 'entity-b'])
      expect(result.entities.map(entity => entity.freeItemCount)).toEqual([0, 0])
    }
  })

  it('accepts Go-valid Unicode concept identities and repeated descriptive lists', async () => {
    const rows = structuredClone(a70())
    const definition = rows.find(row => row.kind === 'concept')!
    Object.assign(definition.payload, { canonical_key: '被保险人', sense_key: '医疗保险', aliases: ['受保人', '受保人'] })
    const overview = rows.find(row => row.kind === 'entity_overview')!
    overview.title = '平安健康险'
    for (const row of rows.filter(row => row.kind === 'field_assertion')) {
      Object.assign(row.payload, { entity_id: '平安健康险', entity_version: '惠享版', conditions: ['续保', '续保'] })
      const proofs = row.payload.evidence as any[]
      proofs.forEach(proof => Object.assign(proof, { knowledge_id: '条款来源', revision_id: '修订一',
        parser_identity: '解析器一', block_id: '段落一' }))
    }
    const parsed = await loadConceptDirectory830G2('wiki-serving', { get: g2Transport(rows) })
    expect(parsed.mode).toBe('g2')
    if (parsed.mode === 'g2') expect(parsed.entities[0].entityID).toBe('平安健康险')
  })

  it.each(['\u0000bad', 'bad\u001f', 'bad\u007f'])('rejects control characters in G2 identities: %j', async bad => {
    const rows = structuredClone(a70())
    ;(rows.find(row => row.kind === 'concept')!.payload as any).canonical_key = bad
    await expect(parseConceptCatalog830G2(rows, scope, current)).rejects.toThrow()
  })

  it.each([
    ['root owner', (_memberID: string, read: any) => { read.member.owner_id = 'entity-foreign' }],
    ['root epoch', (_memberID: string, read: any) => { read.activation_epoch = 5 }],
    ['root identity', (_memberID: string, read: any) => { read.member.member_id = `free_wiki_${H(888)}` }],
    ['root related member', (memberID: string, read: any) => {
      if (memberID.startsWith('entity_overview_')) read.related_members[0].content = 'drift'
    }],
  ])('rejects %s drift from the pinned root read', async (_name, mutate) => {
    await expect(loadConceptDirectory830G2('wiki-serving', { get: g2Transport(a70(), mutate) })).rejects.toThrow()
  })

  it.each([
    ['duplicate member', (rows: ReturnType<typeof a70>) => [...rows, structuredClone(rows[0])]],
    ['missing overview', (rows: ReturnType<typeof a70>) => rows.filter(row => row.kind !== 'entity_overview')],
    ['digest drift', (rows: ReturnType<typeof a70>) => { rows[0].member_digest = 'bad'; return rows }],
    ['payload drift', (rows: ReturnType<typeof a70>) => { (rows[0].payload as any).foreign = true; return rows }],
    ['overview closure drift', (rows: ReturnType<typeof a70>) => { (rows.find(r => r.kind === 'entity_overview')!.payload as any).member_ids = []; return rows }],
    ['mixed G1/G2', (rows: ReturnType<typeof a70>) => { rows.push(snapshot('overview', `page_${H(9)}`, 'old', '', { contract: 'entity-overview-page.830.g1.v1' }, 900)); return rows }],
  ])('rejects %s without a legacy fallback', async (_name, mutate) => {
    await expect(parseConceptCatalog830G2(mutate(structuredClone(a70())), scope, current)).rejects.toThrow()
  })

  it('positively recognizes frozen G1 overview rather than G2 entity_overview', async () => {
    const vector = JSON.parse(readFileSync(new URL('../../../../harness/tests/fixtures/entity_page_graph_830_g1_contract_vector.json', import.meta.url), 'utf8'))
    const rows = vector.members.map((m: any) => ({ kind: m.page_kind, logical_slug: m.page_id,
      revision_id: m.payload_sha256, member_digest: m.member_digest, title: m.short_title,
      content: '', payload: m.payload }))
    const result = await parseConceptCatalog830G2(rows, scope, current)
    expect(result).toEqual(expect.objectContaining({ mode: 'entity-g1', entityID: vector.entity_id }))
    expect(rows.some((row: any) => row.kind === 'overview')).toBe(true)
    expect(rows.some((row: any) => row.kind === 'entity_overview')).toBe(false)
  })

  it.each([
    ['extra payload key', (rows: any[]) => { rows.find(row => row.kind === 'field').payload.foreign = true }],
    ['entity drift', (rows: any[]) => { rows.find(row => row.kind === 'overview').payload.entity_id = 'other-entity' }],
    ['overview closure drift', (rows: any[]) => { rows.find(row => row.kind === 'overview').payload.field_assertions.pop() }],
    ['section closure drift', (rows: any[]) => { rows.find(row => row.kind === 'section').payload.field_assertions.pop() }],
  ])('rejects frozen G1 %s rather than loosely selecting legacy', async (_name, mutate) => {
    const vector = JSON.parse(readFileSync(new URL('../../../../harness/tests/fixtures/entity_page_graph_830_g1_contract_vector.json', import.meta.url), 'utf8'))
    const rows = vector.members.map((m: any) => ({ kind: m.page_kind, logical_slug: m.page_id,
      revision_id: m.payload_sha256, member_digest: m.member_digest, title: m.short_title,
      content: '', payload: structuredClone(m.payload) }))
    mutate(rows)
    await expect(parseConceptCatalog830G2(rows, scope, current)).rejects.toThrow()
  })

  it('positively recognizes old Schema/C6 rows and rejects unknown-only sets', async () => {
    const legacy = [
      snapshot('root', 'root', 'root', '', { contract: 'schema-root-page.v1' }, 1),
      snapshot('section', 'section-a', 'section', '', { contract: 'schema-section-page.v1' }, 2),
      snapshot('field', 'field-a', 'field', '', { contract: 'schema-field-page.v1' }, 3),
    ]
    expect((await parseConceptCatalog830G2(legacy, scope, current)).mode).toBe('schema-legacy')
    await expect(parseConceptCatalog830G2([
      snapshot('mystery', 'mystery', 'mystery', '', {}, 4),
    ], scope, current)).rejects.toThrow()
  })

  it('positively recognizes the exact 1/7/67 stored C6 envelope and rejects partial or mixed C6', async () => {
    const c6 = Array.from({ length: 75 }, (_, i) => {
      const kind = i === 0 ? 'root' : i <= 7 ? 'section' : 'field'
      const identity = i === 0 ? 'entity-a@596-1' : kind === 'section' ? `section-${i}` : `field-${i - 7}`
      const logical = `${kind}:${identity}`
      const body = kind === 'root' ? { entity_version_id: identity }
        : kind === 'section' ? { section_id: identity } : { field_id: identity, schema_order: i - 7 }
      const payload = { contract: 'schema-wiki-isolated-r1-member.815.v1', candidate_sha256: H(700),
        c5_manifest_sha256: H(701), c5_preview_sha256: H(702), quality_status: 'NOT_EVALUATED',
        mvp_status: 'NOT_ACCEPTED', production_status: 'NOT_FOR_PRODUCTION', publishing: false,
        member_kind: kind, body }
      return snapshot(kind, logical, identity, JSON.stringify(payload), payload, 800 + i)
    })
    c6.forEach(row => { row.revision_id = H(701) })
    expect((await parseConceptCatalog830G2(c6, scope, current)).mode).toBe('schema-legacy')
    await expect(parseConceptCatalog830G2(c6.slice(0, 74), scope, current)).rejects.toThrow()
    const mixed = structuredClone(c6)
    mixed[8].payload = { contract: 'schema-field-page.v1' }
    await expect(parseConceptCatalog830G2(mixed, scope, current)).rejects.toThrow()
  })
})
