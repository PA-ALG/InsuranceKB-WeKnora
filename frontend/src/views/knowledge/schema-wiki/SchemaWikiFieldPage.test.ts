// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import zhCN from '../../../i18n/locales/zh-CN.ts'
import SchemaWikiFieldPage from './SchemaWikiFieldPage.vue'
import { parseSchemaFieldPage, parseSchemaWikiScope } from './schemaWikiContract.ts'

const H = (value: string) => value.repeat(64)

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
      props: { fieldPage, scope, releaseId: 'release-596-1' },
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
})
