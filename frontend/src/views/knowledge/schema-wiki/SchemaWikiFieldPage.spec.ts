// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import zhCN from '../../../i18n/locales/zh-CN.ts'
import SchemaWikiFieldPage from './SchemaWikiFieldPage.vue'
import { parseSchemaFieldPage, parseSchemaWikiScope } from './schemaWikiContract.ts'

const H = (value: string) => value.repeat(64)
const inactivePreviewTransport = {
  getAuthority: async () => ({}),
  getBytesByToken: async () => new Uint8Array([1]),
}

function citation(id: string, pageNumber: number) {
  return {
    contract: 'citation-target.v1',
    citation_id: id,
    source_role: 'terms',
    space_id: 'a8751a40-83ce-55c8-a160-079b283483ca',
    entity_version_id: 'ping-an-e-sheng-bao@596-1',
    knowledge_id: 'knowledge-terms',
    chunk_id: `chunk-${pageNumber}`,
    source_revision_id: 'revision-terms-r1',
    parse_attempt_id: 'parse-attempt-r1',
    parsed_document_sha256: H('1'),
    parse_manifest_sha256: H('2'),
    page_number: pageNumber,
    locator_ref: `block-${pageNumber}`,
    bbox: {
      coordinate_system: 'normalized_0_1e6',
      page_width: 1_000_000,
      page_height: 1_000_000,
      x0: 100_000,
      y0: 200_000,
      x1: 800_000,
      y1: 240_000,
    },
    quote_snapshot: `第 ${pageNumber} 页冻结原文`,
    quote_sha256: H(pageNumber === 2 ? '3' : '4'),
    content_snapshot_sha256: H(pageNumber === 2 ? '5' : '6'),
    logical_member_ref: 'field:entry_age_range',
    citation_sha256: H(pageNumber === 2 ? '7' : '8'),
  }
}

describe('SchemaWikiFieldPage unknown coverage', () => {
  it('renders an evidence-free unknown page without residual, pending, citation, or page-one fallback', () => {
    const fieldPage = parseSchemaFieldPage({
      contract: 'schema-field-page.v1',
      field_id: 'coverage_gap_field',
      state: 'unknown',
      value_snapshot: null,
      citations: [],
      evidence_receipt_sha256s: [],
      review_item_reason: 'FIELD_UNKNOWN',
      unknown_reason: 'NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS',
      field_page_sha256: H('f'),
    }, { fieldId: 'coverage_gap_field', fieldPageSha256: H('f') })
    const scope = parseSchemaWikiScope({
      version: 'schema-wiki-scope.v1',
      space_id: 'space-596-1',
      raw_kb_id: 'raw-kb-596-1',
      wiki_kb_id: 'wiki-kb-596-1',
      scope_sha256: H('a'),
    })
    const unknownLabel = zhCN.knowledgeEditor.wikiBrowser.schemaUnknown
    const wrapper = mount(SchemaWikiFieldPage, {
      props: {
        fieldPage,
        fieldDisplayName: '覆盖缺口字段',
        scope,
        releaseId: 'release-596-1',
        activationEpoch: 1,
        previewTransport: inactivePreviewTransport,
      },
      global: {
        mocks: {
          $t: (key: string) => key === 'knowledgeEditor.wikiBrowser.schemaUnknown'
            ? unknownLabel
            : key,
        },
      },
    })

    expect(unknownLabel).toBe('当前材料未提供，待后续材料补充')
    expect(wrapper.attributes('data-field-state')).toBe('unknown')
    expect(wrapper.get('.schema-wiki-field__unknown').text()).toBe(unknownLabel)
    expect(wrapper.find('.schema-wiki-field__value').exists()).toBe(false)
    expect(wrapper.find('.schema-wiki-field__citations').exists()).toBe(false)
    expect(wrapper.find('.schema-wiki-field__preview-status').exists()).toBe(false)
    expect(wrapper.text()).not.toMatch(/residual|待人工|待审核|pending|p\.1|page.?1/i)
    expect(fieldPage.value_snapshot).toBeNull()
    expect(fieldPage.citations).toEqual([])
    expect(fieldPage.evidence_receipt_sha256s).toEqual([])
    expect(fieldPage.unknown_reason).toBe('NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS')
  })

  it('renders an ordinary unknown as undetermined without value, Evidence, citation, or page-one fallback', () => {
    const fieldPage = parseSchemaFieldPage({
      contract: 'schema-field-page.v1',
      field_id: 'ordinary_unknown_field',
      state: 'unknown',
      value_snapshot: null,
      citations: [],
      evidence_receipt_sha256s: [],
      review_item_reason: 'FIELD_UNKNOWN',
      unknown_reason: 'FIELD_UNKNOWN',
      field_page_sha256: H('e'),
    }, { fieldId: 'ordinary_unknown_field', fieldPageSha256: H('e') })
    const scope = parseSchemaWikiScope({
      version: 'schema-wiki-scope.v1',
      space_id: 'space-596-1',
      raw_kb_id: 'raw-kb-596-1',
      wiki_kb_id: 'wiki-kb-596-1',
      scope_sha256: H('a'),
    })
    const wrapper = mount(SchemaWikiFieldPage, {
      props: {
        fieldPage,
        fieldDisplayName: '普通未知字段',
        scope,
        releaseId: 'release-596-1',
        activationEpoch: 1,
        previewTransport: inactivePreviewTransport,
      },
      global: {
        mocks: {
          $t: (key: string) => key === 'knowledgeEditor.wikiBrowser.schemaUndetermined'
            ? zhCN.knowledgeEditor.wikiBrowser.schemaUndetermined
            : key,
        },
      },
    })

    expect(wrapper.get('.schema-wiki-field__unknown').text()).toBe('尚未确定')
    expect(wrapper.find('.schema-wiki-field__value').exists()).toBe(false)
    expect(wrapper.find('.schema-wiki-field__citations').exists()).toBe(false)
    expect(wrapper.find('.schema-wiki-field__preview-status').exists()).toBe(false)
    expect(wrapper.text()).not.toMatch(/当前材料未提供|p\.1|page.?1/i)
  })
})

describe('SchemaWikiFieldPage MVP presentation', () => {
  it('renders the Chinese display name as the title and the stable field id as secondary text', () => {
    const fieldPage = parseSchemaFieldPage({
      contract: 'schema-field-page.v1',
      field_id: 'sales_status',
      state: 'unknown',
      value_snapshot: null,
      citations: [],
      evidence_receipt_sha256s: [],
      review_item_reason: 'FIELD_UNKNOWN',
      unknown_reason: 'FIELD_UNKNOWN',
      field_page_sha256: H('d'),
    }, { fieldId: 'sales_status', fieldPageSha256: H('d') })
    const scope = parseSchemaWikiScope({
      version: 'schema-wiki-scope.v1',
      space_id: 'space-596-1',
      raw_kb_id: 'raw-kb-596-1',
      wiki_kb_id: 'wiki-kb-596-1',
      scope_sha256: H('a'),
    })
    const wrapper = mount(SchemaWikiFieldPage, {
      props: {
        fieldPage,
        fieldDisplayName: '销售状态',
        scope,
        releaseId: 'release-596-1',
      } as never,
      global: { mocks: { $t: (key: string) => key } },
    })

    expect(wrapper.get('h2').text()).toBe('销售状态')
    expect(wrapper.get('[data-testid="schema-field-id"]').text()).toBe('sales_status')
  })

  it('opens the existing active citation viewer from one stable source action', async () => {
    const fieldPage = parseSchemaFieldPage({
      contract: 'schema-field-page.v1',
      field_id: 'entry_age_range',
      state: 'present',
      value_snapshot: '被保险人年龄范围',
      citations: [citation('citation-source-1', 2), citation('citation-source-2', 3)],
      evidence_receipt_sha256s: [H('9')],
      review_item_reason: null,
      unknown_reason: null,
      field_page_sha256: H('b'),
    }, { fieldId: 'entry_age_range', fieldPageSha256: H('b') })
    const scope = parseSchemaWikiScope({
      version: 'schema-wiki-scope.v1',
      space_id: 'a8751a40-83ce-55c8-a160-079b283483ca',
      raw_kb_id: 'b1f1764c-443d-46b8-98e3-d5aa5e55eb42',
      wiki_kb_id: '8d5695de-f255-42d5-9a41-042ba86e97b9',
      scope_sha256: H('a'),
    })
    const wrapper = mount(SchemaWikiFieldPage, {
      attachTo: document.body,
      props: {
        fieldPage,
        fieldDisplayName: '投保年龄',
        scope,
        releaseId: 'release-596-1',
        activationEpoch: 2,
        previewTransport: inactivePreviewTransport,
      } as never,
      global: {
        mocks: {
          $t: (key: string) => key === 'knowledgeEditor.wikiBrowser.schemaCitation'
            ? '查看原文'
            : key,
        },
        stubs: {
          SettingDrawer: {
            name: 'SettingDrawer',
            props: ['visible'],
            emits: ['update:visible'],
            template: '<aside v-if="visible" data-testid="active-source-drawer"><slot /></aside>',
          },
          SchemaCitationViewer: {
            name: 'SchemaCitationViewer',
            props: ['request', 'previewTransport', 'pdfPort'],
            template: '<div data-testid="active-citation-viewer">{{ request.citation_id }}</div>',
          },
        },
      },
    })

    expect(wrapper.findAll('[data-testid="active-source-action"]')).toHaveLength(1)
    await wrapper.get('[data-testid="active-source-action"]').trigger('click')
    expect(wrapper.findAll('[data-testid="active-source-option"]')).toHaveLength(2)
    expect(wrapper.getComponent({ name: 'SchemaCitationViewer' }).props('request')).toEqual({
      release_id: 'release-596-1',
      activation_epoch: 2,
      field_id: 'entry_age_range',
      citation_id: 'citation-source-1',
    })
  })
})
