// @vitest-environment happy-dom
// S3d-4 acceptance (protected, written by Claude): long field values open in a compact version
// (item names, or the first lines) with a switch to the full version; the common "原文依据" origin
// stays readable but out of sight (Spec docs/design/slices/S3d-4-字段取值排版.md §3.2).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import EnterpriseEntity from './EnterpriseEntity.vue'
import EnterpriseField from './EnterpriseField.vue'
import { readRelease } from './enterpriseApi'
import type { FieldView } from './releaseView'

const plugins = () => [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })]
const squash = (text: string) => text.replace(/\s+/g, '')

function fieldView(value: FieldView['value'], origin = 'SOURCE_SUPPORTED', evidenceCount = 2): FieldView {
  return { slug: 'P1/f', title: '保险责任', state: 'present', value, origin, evidenceCount }
}

function field(view: FieldView) {
  return mount(EnterpriseField, { props: { field: view }, global: { plugins: plugins() } })
}

const body = (n: number) => `被保险人经医院确诊初次发生合同所定义的第${n}类情形，且此前未发生过其他情形的，我们按照基本保险金额的${n}0%给付。`
const LONG_LIST = [1, 2, 3].map(n => `${n}. 第${n}项保险金：${body(n)}${body(n)}`).join('')
const LONG_PLAIN = '本合同约定的内容以保险单载明为准，'.repeat(20) + '完。'

afterEach(() => { vi.resetAllMocks() })

describe('short values', () => {
  it('show the value as it is with only the source buttons', () => {
    const view = field(fieldView('90日'))
    expect(view.text()).toContain('90日')
    expect(view.find('[data-toggle]').exists()).toBe(false)
    expect(view.findAll('details')).toHaveLength(0)
    expect(view.findAll('button').map(button => button.text())).toEqual(['出处 1', '出处 2'])
  })

  it('show a short numbered value as an open list', () => {
    const view = field(fieldView('1. 年交：每年一次。2. 月交：每月一次。'))
    expect(view.findAll('[data-item]')).toHaveLength(2)
    expect(view.findAll('details')).toHaveLength(0)
    expect(view.find('[data-toggle]').exists()).toBe(false)
  })
})

describe('long numbered values', () => {
  it('open compact with item names only and switch to the full version and back', async () => {
    const view = field(fieldView(LONG_LIST))
    const toggle = view.get('[data-toggle]')
    expect(toggle.text()).toBe('查看完整版')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(view.text()).toContain('共 3 项')
    const items = view.findAll('details[data-item]')
    expect(items).toHaveLength(3)
    expect(items.map(item => (item.element as HTMLDetailsElement).open)).toEqual([false, false, false])
    expect(items.map(item => item.get('summary').text())).toEqual([
      expect.stringContaining('第1项保险金：'),
      expect.stringContaining('第2项保险金：'),
      expect.stringContaining('第3项保险金：'),
    ])

    await toggle.trigger('click')
    expect(toggle.text()).toBe('收起')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(view.findAll('details[data-item]').map(item => (item.element as HTMLDetailsElement).open)).toEqual([true, true, true])
    expect(squash(view.text())).toContain(squash(LONG_LIST))

    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(view.findAll('details[data-item]').map(item => (item.element as HTMLDetailsElement).open)).toEqual([false, false, false])
  })

  it('keeps the source buttons and never opens a source when switching', async () => {
    const view = field(fieldView(LONG_LIST))
    await view.get('[data-toggle]').trigger('click')
    expect(view.emitted('open')).toBeUndefined()
    const sources = view.findAll('button').filter(button => button.text().startsWith('出处'))
    expect(sources.map(button => button.text())).toEqual(['出处 1', '出处 2'])
    await sources[1].trigger('click')
    expect(view.emitted('open')).toEqual([[1]])
  })
})

describe('short items', () => {
  it('are shown whole, and many of them flow as one wrapped list', () => {
    const names = Array.from({ length: 30 }, (_, i) => `${i + 1}、第${i + 1}种特定疾病名称；`).join('')
    const view = field(fieldView(`保障的疾病如下：${names}`))
    expect(view.find('[data-toggle]').exists()).toBe(true)
    expect(view.findAll('details')).toHaveLength(0)
    expect(view.findAll('[data-item]')).toHaveLength(30)
    expect(view.find('.ek-outline--flow').exists()).toBe(true)
    expect(squash(view.text())).toContain(squash(names))
  })

  it('still flow when a few items are long', () => {
    const names = Array.from({ length: 9 }, (_, i) => `${i + 1}、第${i + 1}种特定疾病名称；`).join('')
    const view = field(fieldView(`${names}10、${body(1)}${body(2)}`))
    expect(view.find('.ek-outline--flow').exists()).toBe(true)
    expect(view.findAll('details')).toHaveLength(0)
    expect(view.findAll('[data-item]')).toHaveLength(10)
  })

  it('stay unfolded next to long items in a compact list', () => {
    const long = [1, 2, 3].map(n => `${n + 1}. 第${n}项保险金：${body(n)}${body(n)}`).join('')
    const view = field(fieldView(`1. 甲：短。${long}`))
    expect(view.findAll('details[data-item]')).toHaveLength(3)
    expect(view.findAll('[data-item]')).toHaveLength(4)
    expect(view.find('.ek-outline--flow').exists()).toBe(false)
  })
})

describe('items that only group their sub-items (review R3 on PR #202)', () => {
  const p = '条件说明。'.repeat(60)

  it.each([
    ['a list element', [`（1）豁免：${p}；（2）给付：${p}。`, '其他']],
    ['a numbered item', `1. （1）豁免：${p}；（2）给付：${p}。2. 其他：${p}`],
  ])('show the sub-items of %s in its place, each folding on its own', async (_, value) => {
    const view = field(fieldView(value as FieldView['value']))
    const summaries = () => view.findAll('details[data-item]').map(item => item.get('summary').text().trim())
    expect(summaries().every(text => text.length > 0 && !/^\d+[.．、]$/.test(text))).toBe(true)
    const named = view.findAll('details[data-item]').filter(item => /（[12]）/.test(item.get('summary').text()))
    expect(named.map(item => item.get('summary').text())).toEqual([
      expect.stringContaining('豁免：'),
      expect.stringContaining('给付：'),
    ])
    for (const item of named) expect(item.element.parentElement?.closest('details')).toBeNull()

    const toggle = view.get('[data-toggle]')
    await toggle.trigger('click')
    expect(view.findAll('details[data-item]').every(item => (item.element as HTMLDetailsElement).open)).toBe(true)
    const text = Array.isArray(value) ? value.join('') : value
    expect(squash(view.text())).toContain(squash(text))
    expect(squash(view.text()).split(squash(p)).length - 1).toBe(Array.isArray(value) ? 2 : 3)
    await toggle.trigger('click')
    expect(view.findAll('details[data-item]').some(item => (item.element as HTMLDetailsElement).open)).toBe(false)
  })
})

describe('long plain values', () => {
  it('are cut to a few lines until the full version is asked for', async () => {
    const view = field(fieldView(LONG_PLAIN))
    const value = view.get('.ek-field__value')
    expect(value.classes()).toContain('ek-field__value--clamped')
    const toggle = view.get('[data-toggle]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(view.text()).not.toContain('共 ')
    await toggle.trigger('click')
    expect(view.get('.ek-field__value').classes()).not.toContain('ek-field__value--clamped')
    expect(squash(view.text())).toContain(squash(LONG_PLAIN))
  })
})

describe('origin labels', () => {
  it('keep 原文依据 readable but visually hidden', () => {
    const origin = field(fieldView('90日')).get('[data-origin]')
    expect(origin.text()).toBe('原文依据')
    expect(origin.classes()).toContain('ek-sr-only')
  })

  it.each([
    ['EXPERT_REVISION', '专家修订'],
    ['MIXED', '原文与整理'],
    ['MODEL_GENERATED', '模型补充'],
  ])('show %s', (originValue, label) => {
    const origin = field(fieldView('90日', originValue)).get('[data-origin]')
    expect(origin.text()).toBe(label)
    expect(origin.classes()).not.toContain('ek-sr-only')
  })
})

it('explains on the entity page that unlabelled content is sourced', async () => {
  vi.mocked(readRelease).mockResolvedValue({
    id: 'rel-1', epoch: 1,
    members: [{
      kind: 'claim', logical_slug: 'P1/f', member_digest: 'd'.repeat(64), access_scope: 'space',
      payload: { subject_ref: 'P1', predicate: 'f', state: 'present', value: '90日', origin: 'SOURCE_SUPPORTED', evidence: [] },
    }],
  })
  const view = mount(EnterpriseEntity, {
    props: { spaceId: 'demo', entityId: 'P1', releaseId: 'rel-1' },
    global: { plugins: plugins(), stubs: { RouterLink: RouterLinkStub, CitationPanel: true } },
  })
  await flushPromises()
  expect(view.get('[data-source-note]').text()).toContain('未标注来源的内容均有原文依据')
})
