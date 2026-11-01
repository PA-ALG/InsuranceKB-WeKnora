// @vitest-environment happy-dom
// SK-3 acceptance (protected, written by Claude): method knowledge on the enterprise pages (Spec
// docs/design/slices/SK-3-销售方法阅读与问答.md §5). A method is an entity whose type a presentation
// profile with knowledge_class "method" serves; its page shows the banner, the notice, its labels by
// navigation names, each list item with its own source, the source materials with their entry date
// and the latest update; a product page links its related methods without their content; the Space
// home directory and the concept keys leave methods out; chat labels method sources apart. Strings
// are checked in zh-CN; every enterprise locale carries the same method keys.
import { flushPromises, mount, RouterLinkStub, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import enUS from './i18n/messages/en-US'
import jaJP from './i18n/messages/ja-JP'
import koKR from './i18n/messages/ko-KR'
import ruRU from './i18n/messages/ru-RU'
import zhMessages from './i18n/messages/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
  readCitation: vi.fn(),
}))

import CitationPanel from './CitationPanel.vue'
import EnterpriseEntity from './EnterpriseEntity.vue'
import { conceptKeys } from './conceptView'
import { readCitation, readRelease } from './enterpriseApi'
import { methodEntityIds, relatedMethods } from './methodView'
import { entityView } from './releaseView'
import { sourceTier, sourceTierLabel } from './sourceTier'
import { spaceHomeView } from './spaceHomeView'
import { MATERIAL_A, methodRelease } from './__tests__/methodFixtures'

function page(props: { spaceId: string; entityId: string; releaseId?: string }) {
  return mount(EnterpriseEntity, {
    props,
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub, CitationPanel: true },
    },
  })
}

function materialCitation(document: string, revisedAt?: string) {
  return {
    release_id: 'rel-m', member: 'sm-1/method_summary', evidence_index: 0, origin: 'SOURCE_SUPPORTED',
    source: { knowledge_id: 'kA', parse_attempt: 1, document, file_sha256: 'ab'.repeat(32),
      ...(revisedAt ? { revised_at: revisedAt } : {}) },
    page: { number: 2 }, start: 0, end: 4, quote: '先问需求', file: '/file',
  }
}

type Target = { name: string; params: { entityId: string } }

afterEach(() => { vi.resetAllMocks() })

describe('method recognition', () => {
  it('takes method titles from the method profile, not a product profile meeting the labels', () => {
    const view = entityView(methodRelease(), 'sm-1')!
    expect(view.profileName).toBe('销售方法')
    expect(view.sections.flatMap(section => section.fields.map(field => field.title))).toEqual(['方法摘要', '步骤', '关键句'])
    expect(entityView(methodRelease(), 'P1')!.sections[0]!.fields.map(field => field.title)).toEqual(['等待期'])
  })

  it('knows the methods and a product’s related methods, family first', () => {
    expect([...methodEntityIds(methodRelease())].sort()).toEqual(['sm-1', 'sm-2', 'sm-3'])
    expect(relatedMethods(methodRelease(), 'P1').map(entry => entry.entityId)).toEqual(['sm-1', 'sm-3'])
    expect(relatedMethods(methodRelease(), 'P2').map(entry => entry.entityId)).toEqual(['sm-3', 'sm-1'])
    expect(relatedMethods(methodRelease(), 'P3')).toEqual([])
    expect(relatedMethods(methodRelease(), 'sm-1')).toEqual([])
  })

  it('leaves methods out of the Space home directory and the concept keys', () => {
    const home = spaceHomeView(methodRelease())
    expect(home.groups.flatMap(group => group.rows.map(row => row.entityId)).sort()).toEqual(['P1', 'P2', 'P3'])
    expect(home.productCount).toBe(3)
    expect(conceptKeys(methodRelease())).toEqual(['waiting_period'])
  })
})

describe('method page', () => {
  it('shows the banner, notice, labels, items with their own sources, materials and update', async () => {
    vi.mocked(readRelease).mockResolvedValue(methodRelease())
    vi.mocked(readCitation).mockResolvedValue(materialCitation('培训A.pptx', '2026-10-29T17:00:00Z'))
    const view = page({ spaceId: 'demo', entityId: 'sm-1', releaseId: 'rel-m' })
    await flushPromises()

    expect(view.get('h1').text()).toBe('需求分析三步法')
    expect(view.get('[data-method-banner]').text()).toBe('销售方法（培训材料，非产品事实）')
    expect(view.get('[data-method-notice]').text()).toBe('含产品信息：以条款与已发布知识为准')
    expect(view.findAll('[data-method-label]').map(label => label.text())).toEqual(['医疗险', '系列：甲医疗系列', '需求分析'])
    const family = view.get('[data-method-family]').findAllComponents(RouterLinkStub)
    expect(family.map((link: VueWrapper<any>) => (link.props('to') as Target).params.entityId)).toEqual(['P1'])

    expect(view.findAll('[data-method-field]').map(field => field.attributes('data-method-field')))
      .toEqual(['sm-1/method_summary', 'sm-1/method_steps', 'sm-1/key_phrases'])
    const items = view.findAll('[data-method-field="sm-1/method_steps"] [data-method-item]')
    expect(items.map(item => item.text())).toEqual([expect.stringContaining('问家庭'), expect.stringContaining('讲保障')])
    expect(view.get('[data-method-field="sm-1/key_phrases"]').text()).toContain('材料未提及')
    expect(view.find('[data-expert-edit]').exists()).toBe(false)

    expect(view.findComponent(CitationPanel).exists()).toBe(false)
    await items[1]!.get('[data-method-source]').trigger('click')
    expect(view.getComponent(CitationPanel).props()).toMatchObject({
      spaceId: 'demo', releaseId: 'rel-m', member: 'sm-1/method_steps', evidence: 1,
    })

    expect(vi.mocked(readCitation).mock.calls).toEqual([['demo', 'rel-m', 'sm-1/method_summary', 0]])
    expect(view.get('[data-method-materials]').text()).toContain('培训A.pptx（入库 2026-10-30）')
    expect(view.get('[data-method-updated]').text()).toBe('更新于 2026-10-30')
  })

  it('reads each material once and keeps the page when a material cannot be read', async () => {
    const release = methodRelease()
    vi.mocked(readRelease).mockResolvedValue(release)
    vi.mocked(readCitation).mockRejectedValue(new Error('down'))
    const view = page({ spaceId: 'demo', entityId: 'sm-1', releaseId: 'rel-m' })
    await flushPromises()
    expect(vi.mocked(readCitation)).toHaveBeenCalledTimes(1)
    expect(view.get('[data-method-materials]').text()).toContain('来源材料暂不可读')
    expect(view.findAll('[data-method-field]')).toHaveLength(3)
    expect(MATERIAL_A).toContain('kA')
  })

  it('shows no notice, family or update for a general method without them', async () => {
    vi.mocked(readRelease).mockResolvedValue(methodRelease())
    vi.mocked(readCitation).mockResolvedValue(materialCitation('培训B.pdf'))
    const view = page({ spaceId: 'demo', entityId: 'sm-2', releaseId: 'rel-m' })
    await flushPromises()
    expect(view.find('[data-method-banner]').exists()).toBe(true)
    expect(view.find('[data-method-notice]').exists()).toBe(false)
    expect(view.find('[data-method-family]').exists()).toBe(false)
    expect(view.find('[data-method-updated]').exists()).toBe(false)
    expect(view.findAll('[data-method-label]').map(label => label.text())).toEqual(['通用'])
    expect(view.get('[data-method-materials]').text()).toContain('培训B.pdf')
  })
})

describe('product page', () => {
  it('links the related methods without their content', async () => {
    vi.mocked(readRelease).mockResolvedValue(methodRelease())
    const view = page({ spaceId: 'demo', entityId: 'P1', releaseId: 'rel-m' })
    await flushPromises()
    const related = view.get('[data-related-methods]')
    expect(related.text()).toContain('相关销售方法')
    const links = related.findAllComponents(RouterLinkStub)
    expect(links.map((link: VueWrapper<any>) => link.text())).toEqual(['需求分析三步法', '说明会邀约法'])
    expect(links.map((link: VueWrapper<any>) => link.props('to'))).toEqual(['sm-1', 'sm-3'].map(entityId => (
      { name: 'enterpriseEntity', params: { spaceId: 'demo', entityId }, query: { release: 'rel-m' } })))
    expect(view.text()).not.toContain('问家庭')
    expect(view.find('[data-method-banner]').exists()).toBe(false)
    expect(readCitation).not.toHaveBeenCalled()
  })

  it('shows nothing for a product without related methods', async () => {
    vi.mocked(readRelease).mockResolvedValue(methodRelease())
    const view = page({ spaceId: 'demo', entityId: 'P3', releaseId: 'rel-m' })
    await flushPromises()
    expect(view.find('[data-related-methods]').exists()).toBe(false)
  })
})

describe('chat source label', () => {
  it('labels method knowledge apart from reviewed product facts', () => {
    const t = (key: string) => key
    expect(sourceTier({ metadata: { source_tier: 'release', knowledge_class: 'method' } })).toBe('method')
    expect(sourceTierLabel('method', t)).toBe('chat.sourceTierMethod')
    expect(sourceTier({ metadata: { source_tier: 'release' } })).toBe('release')
    expect(sourceTier({ metadata: { source_tier: 'raw_text', knowledge_class: 'method' } })).toBe('raw_text')
    expect((zhMessages as any).chat.sourceTierMethod).toBe('销售方法（培训材料，非产品事实）')
  })
})

describe('method strings', () => {
  const keys = (messages: any): string[] => {
    const out: string[] = []
    const walk = (value: any, path: string) => {
      if (value && typeof value === 'object') for (const [key, child] of Object.entries(value)) walk(child, path ? `${path}.${key}` : key)
      else out.push(path)
    }
    walk(messages?.enterpriseKnowledge?.method, '')
    return out.sort()
  }

  it('exist in every enterprise locale with the same keys', () => {
    const expected = keys(zhMessages)
    expect(expected).toEqual(expect.arrayContaining([
      'banner', 'notices.product_info', 'labels', 'family', 'source', 'materials', 'material', 'materialsLoading',
      'materialsFailed', 'updated', 'related',
    ]))
    for (const messages of [enUS, jaJP, koKR, ruRU]) {
      expect(keys(messages)).toEqual(expected)
      expect(typeof (messages as any).chat.sourceTierMethod).toBe('string')
    }
  })
})
