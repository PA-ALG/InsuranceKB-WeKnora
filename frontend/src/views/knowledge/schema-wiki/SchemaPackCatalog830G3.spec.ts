// @vitest-environment happy-dom

import { readFileSync } from 'node:fs'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SchemaPackCatalog830G3 from './SchemaPackCatalog830G3.vue'

const catalog = JSON.parse(readFileSync(
  '../internal/handler/schema_pack_catalog_830_g3.generated.json',
  'utf8',
))

describe('SchemaPackCatalog830G3', () => {
  it('uses one read-only renderer for all packs, variable nodes, and workbook metadata', async () => {
    const wrapper = mount(SchemaPackCatalog830G3, { props: { catalog } })

    expect(wrapper.findAll('[data-testid="catalog-pack-action"]')).toHaveLength(11)
    expect(wrapper.get('[data-testid="catalog-counts"]').text()).toContain('11 个产品结构 · 801 个字段')
    expect(wrapper.text()).toContain('结构待确认')
    expect(wrapper.text()).toContain('业务质量待评估')
    expect(wrapper.text()).toContain('工作簿未填写')
    expect(wrapper.findAll('[data-testid="catalog-section-action"]')).toHaveLength(7)
    expect(wrapper.findAll('th').map(header => header.text())).toEqual([
      '业务分类', '字段名', '取值', '英文名', '说明', '取值来源',
      '知识形成方式', '知识角色', '公共字段', '其它适用险种', '使用频次',
    ])
    expect(wrapper.find('[data-testid="catalog-edit-action"]').exists()).toBe(false)

    await wrapper.get('[data-pack-id="schemapack_critical_illness_insurance"]').trigger('click')
    expect(wrapper.findAll('[data-testid="catalog-section-action"]')).toHaveLength(8)
    expect(wrapper.get('[data-testid="catalog-selected-pack"]').text()).toContain('重疾险')
  })
})
