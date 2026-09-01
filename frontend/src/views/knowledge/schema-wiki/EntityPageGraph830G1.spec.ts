// @vitest-environment happy-dom

import { flushPromises, mount, type Stubs } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiState = vi.hoisted(() => ({
  calls: [] as unknown[][],
  result: undefined as unknown,
  scope: undefined as unknown,
  failure: null as Error | null,
}))
const requestState = vi.hoisted(() => ({
  calls: [] as unknown[][],
  result: undefined as unknown,
  failure: null as Error | null,
}))
const routeLoadState = vi.hoisted(() => ({ knowledgeBaseLoads: 0 }))

vi.mock('@/api/schema-wiki/entityPageGraph830G1.ts', () => ({
  readEntityPageGraph830G1: async (...args: unknown[]) => {
    apiState.calls.push(args)
    if (apiState.failure) throw apiState.failure
    return apiState.result
  },
  readEntityPageGraphSession830G1: async (...args: unknown[]) => {
    apiState.calls.push(args)
    if (apiState.failure) throw apiState.failure
    return { scope: apiState.scope, read: apiState.result }
  },
  createEntityPageGraphPreparationCitationTransport830G1: (
    scopeValue: typeof scope,
    preparationID: string,
    entityID: string,
    fullCitationID: string,
  ) => ({
    getAuthority: async (request: { field_id: string }) => {
      requestState.calls.push([
        `/api/v1/knowledgebase/${scopeValue.wiki_kb_id}/wiki/release-scopes/${scopeValue.space_id}`
          + `/raw/${scopeValue.raw_kb_id}/schema/preparations/${preparationID}`
          + `/entities/${entityID}/fields/${request.field_id}/citations/${fullCitationID}/preview`,
      ])
      if (requestState.failure) throw requestState.failure
      return requestState.result
    },
    getBytesByToken: async () => new Uint8Array([1]),
  }),
}))
vi.mock('@/utils/request', () => ({
  get: async (...args: unknown[]) => {
    requestState.calls.push(args)
    if (requestState.failure) throw requestState.failure
    return requestState.result
  },
}))
vi.mock('@/views/knowledge/KnowledgeBase.vue', () => {
  routeLoadState.knowledgeBaseLoads += 1
  return { default: { name: 'KnowledgeBase' } }
})

import appRouter from '@/router'
import { parseSchemaWikiScope } from './schemaWikiContract.ts'
import EntityPageGraph830G1 from './EntityPageGraph830G1.vue'

const JOIN_RECEIPT_SHA256 = '3'.repeat(64)
const scope = parseSchemaWikiScope({
  version: 'schema-wiki-scope.v1',
  space_id: 'space-1',
  raw_kb_id: 'raw-1',
  wiki_kb_id: 'wiki-1',
  scope_sha256: '4'.repeat(64),
})

function citation() {
  return {
    contract: 'entity-page-exact-citation.830.g1.v1',
    citation_id: `citation_${JOIN_RECEIPT_SHA256}`,
    join_receipt_sha256: JOIN_RECEIPT_SHA256,
    evidence_receipt_sha256: '5'.repeat(64),
    source_role: 'terms',
    source_sha256: '6'.repeat(64),
    source_revision_id: 'revision-1',
    knowledge_id: 'knowledge-1',
    chunk_id: 'chunk-1',
    parse_attempt_id: 'parse-1',
    parsed_document_sha256: '7'.repeat(64),
    parse_manifest_sha256: '8'.repeat(64),
    page_number: 12,
    locator_kind: 'PDF_PAGE_BBOX',
    locator_ref: 'page-12-block-1',
    locator_content_sha256: '9'.repeat(64),
    bbox: {
      coordinate_system: 'normalized_0_1e6',
      page_width: 1_000_000,
      page_height: 1_000_000,
      x0: 100_000,
      y0: 200_000,
      x1: 800_000,
      y1: 240_000,
    },
    quote_snapshot: '第 12 页冻结原文',
    quote_sha256: 'a'.repeat(64),
    citation_sha256: 'b'.repeat(64),
  }
}

function fieldRead(
  state: 'present' | 'absent_explicitly' | 'unknown' = 'unknown',
  citations: ReadonlyArray<ReturnType<typeof citation>> = [],
) {
  return {
    contract: 'entity-page-read.830.g1.v1', read_mode: 'current', release_id: 'release-1',
    activation_epoch: 2, manifest_sha256: 'a'.repeat(64), entity_id: 'entity-1',
    entity_version_id: 'entity-1@v1', display_name: '测试产品', classification_display_name: '医疗保险',
    profile: {
      contract: 'presentation-profile.v1', profile_id: 'profile-1', profile_version: '1',
      schema_pack_id: 'pack-1', schema_version: '1', schema_pack_sha256: 'b'.repeat(64),
      profile_sha256: 'c'.repeat(64),
      sections: [
        { section_key: 'section-a', display_name: '分类甲', fields: [{ field_key: 'field-1', short_title: '字段一' }] },
        { section_key: 'section-b', display_name: '分类乙', fields: [{ field_key: 'field-2', short_title: '字段二' }] },
      ],
    },
    member: {
      contract: 'entity-page-member.830.g1.v1', page_id: 'page-1',
      namespace: 'urn:jlx:wiki:space-1:entity:entity-1:field:field-1',
      route: '/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/fields/field-1',
      page_kind: 'field', stable_key: 'field-1', short_title: '字段一', space_id: 'space-1',
      wiki_kb_id: 'wiki-1', entity_id: 'entity-1', release_id: 'release-1',
      candidate_sha256: 'd'.repeat(64), claim_set_sha256: 'e'.repeat(64),
      evidence_authority_sha256: 'f'.repeat(64), schema_pack_sha256: 'b'.repeat(64),
      profile_sha256: 'c'.repeat(64), payload_sha256: '1'.repeat(64), member_digest: '2'.repeat(64),
      payload: {
        contract: 'field-assertion-page.830.g1.v1', field_key: 'field-1', reference: {}, state,
        value_snapshot: state === 'unknown' ? null : '字段值', display_value: state === 'unknown' ? null : '字段值',
        unknown_reason: state === 'unknown' ? 'FIELD_UNKNOWN' : null,
        source_typed_reason: state === 'unknown' ? 'SOURCE_NOT_AVAILABLE' : null,
        citations,
      },
    },
  }
}

const settingDrawerStub = {
  name: 'SettingDrawer',
  props: ['visible', 'description'],
  emits: ['update:visible'],
  template: '<aside v-if="visible" data-testid="entity-source-drawer"><slot /></aside>',
}

const citationViewerStub = {
  name: 'SchemaCitationViewer',
  props: ['request', 'previewTransport', 'pdfPort'],
  template: '<div data-testid="entity-citation-viewer">{{ request.citation_id }}</div>',
}

async function mountAt(path: string, stubs: Stubs = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/platform/knowledge-bases/:kbId/schema-wiki/entities/:entityId/overview', name: 'entityPageOverview830G1', component: EntityPageGraph830G1 },
      { path: '/platform/knowledge-bases/:kbId/schema-wiki/entities/:entityId/sections/:sectionKey', name: 'entityPageSection830G1', component: EntityPageGraph830G1 },
      { path: '/platform/knowledge-bases/:kbId/schema-wiki/entities/:entityId/fields/:fieldKey', name: 'entityPageField830G1', component: EntityPageGraph830G1 },
      { path: '/platform/knowledge-bases/:kbId/schema-wiki/entities/:entityId/free-wiki', name: 'entityPageFreeWiki830G1', component: EntityPageGraph830G1 },
    ],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(EntityPageGraph830G1, { global: { plugins: [router], stubs } })
  await flushPromises()
  return wrapper
}

describe('EntityPageGraph830G1', () => {
  beforeEach(() => {
    apiState.calls = []
    apiState.result = undefined
    apiState.scope = scope
    apiState.failure = null
    requestState.calls = []
    requestState.result = undefined
    requestState.failure = null
    routeLoadState.knowledgeBaseLoads = 0
  })

  it('renders profile-driven navigation, short title, full namespace and unknown state', async () => {
    apiState.result = fieldRead()
    const wrapper = await mountAt('/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/fields/field-1?release_id=release-1')
    expect(wrapper.findAll('[data-testid="entity-section-link"]')).toHaveLength(2)
    expect(wrapper.get('h1').text()).toBe('字段一')
    expect(wrapper.get('[data-testid="entity-page-namespace"]').text()).toContain(':field:field-1')
    expect(wrapper.get('[data-testid="entity-field-unknown"]').text()).toContain('尚未确定')
    expect(apiState.calls).toHaveLength(1)
    expect(apiState.calls[0][2]).toBe('release-1')
  })

  it('shows an explicit failure and never retries', async () => {
    apiState.failure = new Error('ENTITY_PAGE_GRAPH_NOT_FOUND')
    const wrapper = await mountAt('/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/fields/field-1')
    expect(wrapper.get('[role="alert"]').text()).toContain('页面读取失败')
    expect(apiState.calls).toHaveLength(1)
  })

  it.each([
    '?release_id=',
    '?release_id=release-one&release_id=release-two',
      '?preparation_id=',
      '?preparation_id=preparation-one&preparation_id=preparation-two',
      '?preparation_id=current',
      '?release_id=release-one&preparation_id=preparation-one',
  ])('fails closed before transport for malformed route query %s', async query => {
    apiState.result = fieldRead()
    const wrapper = await mountAt(
      `/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/fields/field-1${query}`,
    )
    expect(wrapper.get('[role="alert"]').text()).toContain('页面读取失败')
    expect(apiState.calls).toEqual([])
  })

  it('loads and preserves one exact Candidate Preview preparation mode', async () => {
    const preparationRead = fieldRead() as ReturnType<typeof fieldRead> & { preparation_id: string }
    preparationRead.read_mode = 'preparation'
    preparationRead.preparation_id = 'preparation-g1'
    apiState.result = preparationRead
    const wrapper = await mountAt(
      '/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/fields/field-1?preparation_id=preparation-g1',
    )

    expect(wrapper.text()).toContain('候选预览')
    expect(apiState.calls).toHaveLength(1)
    expect(apiState.calls[0][2]).toBeUndefined()
    expect(apiState.calls[0][4]).toBe('preparation-g1')
    const sectionLink = wrapper.get('[data-testid="entity-section-link"]')
    expect(sectionLink.attributes('href')).toContain('preparation_id=preparation-g1')
  })

  it('lazy-loads the entity page component directly for all four semantic URLs', async () => {
    const paths = [
      '/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/overview',
      '/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/sections/section-a',
      '/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/fields/field-1',
      '/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/free-wiki',
    ]
    for (const path of paths) {
      const resolved = appRouter.resolve(path)
      const record = appRouter.getRoutes().find(route => route.name === resolved.name)
      const loader = record?.components?.default as undefined | (() => Promise<{ default: unknown }>)
      expect(loader).toBeTypeOf('function')
      expect((await loader!()).default).toBe(EntityPageGraph830G1)
    }
    expect(routeLoadState.knowledgeBaseLoads).toBe(0)
  })

  it('opens the existing citation viewer with the exact Active tuple and frozen 815 citation identity', async () => {
    apiState.result = fieldRead('present', [citation()])
    requestState.result = { success: true, data: { authority: true } }
    const wrapper = await mountAt(
      '/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/fields/field-1',
      { SettingDrawer: settingDrawerStub, SchemaCitationViewer: citationViewerStub },
    )

    await wrapper.get('[data-testid="entity-source-action"]').trigger('click')
    const viewer = wrapper.getComponent({ name: 'SchemaCitationViewer' })
    const request = viewer.props('request') as {
      release_id: string
      activation_epoch: number
      field_id: string
      citation_id: string
    }
    expect(request).toEqual({
      release_id: 'release-1',
      activation_epoch: 2,
      field_id: 'field-1',
      citation_id: `citation-${JOIN_RECEIPT_SHA256.slice(0, 24)}`,
    })

    const previewTransport = viewer.props('previewTransport') as {
      getAuthority(value: typeof request): Promise<unknown>
    }
    await previewTransport.getAuthority(request)
    expect(requestState.calls).toEqual([[
      '/api/v1/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/schema'
      + `/releases/release-1/fields/field-1/citations/citation-${JOIN_RECEIPT_SHA256.slice(0, 24)}/preview`,
    ]])
  })

  it('uses the full G1 citation ID as Candidate Preview route authority', async () => {
    const preparationRead = fieldRead('present', [citation()]) as ReturnType<typeof fieldRead> & { preparation_id: string }
    preparationRead.read_mode = 'preparation'
    preparationRead.preparation_id = 'preparation-g1'
    apiState.result = preparationRead
    requestState.result = { success: true, data: { authority: true } }
    const wrapper = await mountAt(
      '/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/fields/field-1?preparation_id=preparation-g1',
      { SettingDrawer: settingDrawerStub, SchemaCitationViewer: citationViewerStub },
    )

    await wrapper.get('[data-testid="entity-source-action"]').trigger('click')
    const viewer = wrapper.getComponent({ name: 'SchemaCitationViewer' })
    const previewTransport = viewer.props('previewTransport') as {
      getAuthority(value: { release_id: string, activation_epoch: number, field_id: string, citation_id: string }): Promise<unknown>
    }
    await previewTransport.getAuthority(viewer.props('request') as never)
    expect(requestState.calls).toEqual([[
      '/api/v1/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/schema'
      + `/preparations/preparation-g1/entities/entity-1/fields/field-1/citations/citation_${JOIN_RECEIPT_SHA256}/preview`,
    ]])
    expect(wrapper.getComponent({ name: 'SettingDrawer' }).props('description')).toBe('候选预览的原始证据')
  })

  it('does not offer a source action for an unknown field', async () => {
    apiState.result = fieldRead('unknown')
    const wrapper = await mountAt(
      '/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/fields/field-1',
      { SettingDrawer: settingDrawerStub, SchemaCitationViewer: citationViewerStub },
    )

    expect(wrapper.find('[data-testid="entity-source-action"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="entity-source-drawer"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="entity-citation-viewer"]').exists()).toBe(false)
    expect(requestState.calls).toEqual([])
  })

  it('labels a pinned source drawer as a fixed release without calling it Active', async () => {
    const pinnedRead = fieldRead('present', [citation()])
    pinnedRead.read_mode = 'pinned'
    apiState.result = pinnedRead
    const wrapper = await mountAt(
      '/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/fields/field-1?release_id=release-1',
      { SettingDrawer: settingDrawerStub, SchemaCitationViewer: citationViewerStub },
    )

    await wrapper.get('[data-testid="entity-source-action"]').trigger('click')
    const description = String(wrapper.getComponent({ name: 'SettingDrawer' }).props('description'))
    expect(description).toBe('固定发布版本的原始证据')
    expect(description).not.toContain('Active')
  })

  it('shows preview transport failure explicitly without quote, current, latest, or content fallback', async () => {
    const exactCitation = citation()
    apiState.result = fieldRead('present', [exactCitation])
    requestState.failure = new Error('transport failed')
    const wrapper = await mountAt(
      '/platform/knowledge-bases/wiki-1/schema-wiki/entities/entity-1/fields/field-1',
      { SettingDrawer: settingDrawerStub },
    )

    await wrapper.get('[data-testid="entity-source-action"]').trigger('click')
    await vi.waitFor(() => {
      expect(wrapper.get('[data-testid="citation-error"]').text()).toBe('PDF_PREVIEW_UNAVAILABLE')
    })
    expect(requestState.calls).toHaveLength(1)
    expect(String(requestState.calls[0][0])).toContain(
      `/releases/release-1/fields/field-1/citations/citation-${JOIN_RECEIPT_SHA256.slice(0, 24)}/preview`,
    )
    expect(JSON.stringify(requestState.calls)).not.toMatch(/current|latest|citation-content/)
    expect(wrapper.text()).not.toContain(exactCitation.quote_snapshot)
  })
})
