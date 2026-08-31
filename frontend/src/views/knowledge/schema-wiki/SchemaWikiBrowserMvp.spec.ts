// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { MEDICAL_SCHEMA67_FIELD_PRESENTATION_ROWS } from './schemaWikiMvpPresentation.ts'

const H = (value: string) => value.repeat(64)
const ENTRY_KB = 'b1f1764c-443d-46b8-98e3-d5aa5e55eb42'
const SERVING_KB = '8d5695de-f255-42d5-9a41-042ba86e97b9'

const apiMocks = vi.hoisted(() => ({
  bootstrap: vi.fn(),
  previewTransport: Object.freeze({
    getAuthority: vi.fn(),
    getBytesByToken: vi.fn(),
  }),
}))

vi.mock('@/api/schema-wiki', () => ({
  bootstrapSchemaWikiClient: apiMocks.bootstrap,
  createSchemaWikiCitationPreviewTransport: vi.fn(() => apiMocks.previewTransport),
}))

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
}))

import SchemaWikiBrowser from './SchemaWikiBrowser.vue'

const sectionSizes = [16, 11, 10, 9, 8, 7, 6]
const sectionHashes = ['4', '5', '6', '7', '8', '9', 'c']
const sectionIds = sectionSizes.map((_, index) => `section-${index + 1}`)
const fieldIds = MEDICAL_SCHEMA67_FIELD_PRESENTATION_ROWS.map(([fieldId]) => fieldId)
const sections = (() => {
  let offset = 0
  return sectionSizes.map((size, index) => {
    const ids = fieldIds.slice(offset, offset + size)
    offset += size
    return {
      contract: 'schema-section-page.v1',
      domain_id: 'medical-insurance',
      domain_sha256: H('1'),
      schema_pack_id: 'medical-schema67.v1',
      schema_version: '1',
      schema_pack_sha256: H('2'),
      entity_id: 'ping-an-e-sheng-bao',
      entity_version_id: 'ping-an-e-sheng-bao@596-1',
      product_version_id: '596-1',
      taxonomy_version: '1',
      taxonomy_sha256: H('3'),
      section_id: sectionIds[index],
      display_name: `分类 ${index + 1}`,
      ordered_field_ids: ids,
      section_page_sha256: H(sectionHashes[index]),
    }
  })
})()

const root = {
  contract: 'schema-root-page.v1',
  domain_id: 'medical-insurance',
  domain_sha256: H('1'),
  schema_pack_id: 'medical-schema67.v1',
  schema_version: '1',
  schema_pack_sha256: H('2'),
  entity_id: 'ping-an-e-sheng-bao',
  entity_version_id: 'ping-an-e-sheng-bao@596-1',
  product_version_id: '596-1',
  taxonomy_version: '1',
  taxonomy_sha256: H('3'),
  product_display_name: '平安 e 生保（导学版）医疗保险',
  ordered_section_ids: sectionIds,
  root_page_sha256: H('b'),
}

describe('SchemaWikiBrowser current MVP experience', () => {
  beforeEach(() => {
    apiMocks.bootstrap.mockReset()
    ;(window as Window & { __RUNTIME_CONFIG__?: Record<string, unknown> }).__RUNTIME_CONFIG__ = {
      SCHEMA_WIKI_MVP_ENTRY_KB_ID: ENTRY_KB,
      SCHEMA_WIKI_MVP_SERVING_KB_ID: SERVING_KB,
      SCHEMA_WIKI_MVP_LABEL: '当前 MVP · 只读',
    }
    apiMocks.bootstrap.mockResolvedValue({
      scope: {
        version: 'schema-wiki-scope.v1',
        space_id: 'space-596-1',
        raw_kb_id: ENTRY_KB,
        wiki_kb_id: SERVING_KB,
        scope_sha256: H('a'),
      },
      getCurrentEntityVersion: vi.fn(async () => ({
        version: 'schema-wiki-current-entity-version.v1',
        entity_id: 'ping-an-e-sheng-bao',
        entity_version_id: 'ping-an-e-sheng-bao@596-1',
        active_release_id: 'release-596-1',
        activation_epoch: 2,
        root,
      })),
      getDomains: vi.fn(async () => [{
        contract: 'knowledge-domain.v1',
        domain_id: 'medical-insurance',
        display_name: '医疗保险',
        domain_sha256: H('1'),
      }]),
      getCurrentTaxonomy: vi.fn(async () => ({
        contract: 'taxonomy-snapshot.v1',
        domain_id: 'medical-insurance',
        taxonomy_version: '1',
        previous_snapshot_sha256: null,
        nodes: [],
        redirects: [],
        taxonomy_sha256: H('3'),
      })),
      getReleaseRoot: vi.fn(async () => root),
      getReleaseSection: vi.fn(async (_releaseId: string, sectionId: string) => (
        sections.find(section => section.section_id === sectionId)
      )),
      getReleaseField: vi.fn(async (_releaseId: string, fieldId: string) => ({
        contract: 'schema-field-page.v1',
        field_id: fieldId,
        state: 'unknown',
        value_snapshot: null,
        citations: [],
        evidence_receipt_sha256s: [],
        review_item_reason: 'FIELD_UNKNOWN',
        unknown_reason: 'FIELD_UNKNOWN',
        field_page_sha256: H('f'),
      })),
    })
  })

  it('uses the serving Wiki while rendering a Chinese-primary 7/67 read-only MVP', async () => {
    const wrapper = mount(SchemaWikiBrowser, {
      props: { knowledgeBaseId: ENTRY_KB },
      global: {
        mocks: { $t: (key: string) => key },
        stubs: {
          SchemaWikiFieldPage: {
            props: ['fieldPage', 'fieldDisplayName'],
            template: '<article data-testid="field-stub">{{ fieldDisplayName }}</article>',
          },
        },
      },
    })
    await flushPromises()

    expect(apiMocks.bootstrap).toHaveBeenCalledWith(SERVING_KB, expect.any(Object))
    expect(wrapper.get('[data-testid="schema-mvp-badge"]').text()).toBe('当前 MVP · 只读')
    expect(wrapper.get('[data-testid="schema-mvp-counts"]').text()).toContain('7 个分类')
    expect(wrapper.get('[data-testid="schema-mvp-counts"]').text()).toContain('67 个字段')
    expect(wrapper.findAll('[data-testid="schema-section-action"]')).toHaveLength(7)
    expect(wrapper.get('[data-testid="schema-field-label"]').text()).toBe('险种代码')
    expect(wrapper.get('[data-testid="schema-field-code"]').text()).toBe('product_code')
    expect(wrapper.get('[data-testid="field-stub"]').text()).toBe('险种代码')
    expect(wrapper.text()).not.toContain('C6-ISOLATED')
  })
})
