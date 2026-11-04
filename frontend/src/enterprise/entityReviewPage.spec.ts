// @vitest-environment happy-dom
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from './i18n/locales/zh-CN'
import enUS from './i18n/locales/en-US'
import jaJP from './i18n/locales/ja-JP'
import koKR from './i18n/locales/ko-KR'
import ruRU from './i18n/locales/ru-RU'

vi.mock('./enterpriseApi', async original => ({
  ...(await original<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(), listReviews: vi.fn(), readReview: vi.fn(), decidePoints: vi.fn(),
}))
import EnterpriseReviews from './EnterpriseReviews.vue'
import { decidePoints, listReviews, readRelease, readReview, type Release, type ReleaseMember, type ReviewDetail } from './enterpriseApi'
import { pointItem, pointResult } from './__tests__/reviewPointFixtures'

type Payload = Record<string, unknown>
const views: ReturnType<typeof mount>[] = []
const member = (kind: string, slug: string, payload: Payload): ReleaseMember => ({
  kind, logical_slug: slug, payload, member_digest: 'a'.repeat(64), access_scope: 'space',
})
const entity = (extra: Payload = {}) => member('entity', 'entity/E1', {
  entity_id: 'E1', entity_type: 'method', names: ['合成方法名称'], identifiers: {}, ...extra,
})
const profile = (notice: string) => member('presentation_profile', 'presentation/demo', {
  entity_types: ['method'], notices: { product_info: notice }, sections: [],
})

async function page(old: ReleaseMember | null, next: ReleaseMember | null, options: { unavailable?: boolean; locale?: string } = {}) {
  const release: Release = { id: 'r1', epoch: 1, members: [...(old ? [old] : []), profile('旧提示说明')] }
  const item = pointItem('c1', { subjects: ['E1'], point_count: 1, pending_points: 1 })
  const detail: ReviewDetail = { ...item, head_release_id: 'r1', blocker: '',
    bundle_members: [...(next ? [next] : []), profile('产品信息以已发布内容为准（合成提示）')],
    bundle_removals: next ? [] : ['entity/E1'], points: [{ slug: 'entity/E1', kind: next ? 'member' : 'removal',
      status: 'pending', decision: null, release_id: null, blocker: '' }] }
  vi.mocked(listReviews).mockResolvedValue([item])
  vi.mocked(readReview).mockResolvedValue(detail)
  if (options.unavailable) vi.mocked(readRelease).mockRejectedValue(new Error('offline'))
  else vi.mocked(readRelease).mockResolvedValue(release)
  const view = mount(EnterpriseReviews, { props: { spaceId: 'demo' }, attachTo: document.body,
    global: { plugins: [createI18n({ legacy: false, locale: options.locale ?? 'zh-CN',
      messages: { 'zh-CN': zhCN, 'en-US': enUS, 'ja-JP': jaJP, 'ko-KR': koKR, 'ru-RU': ruRU } })],
    stubs: { RouterLink: RouterLinkStub } } })
  views.push(view)
  await flushPromises()
  return { view, card: view.get('[data-point="entity/E1"]') }
}
afterEach(() => { views.splice(0).forEach(view => view.unmount()); vi.resetAllMocks() })

describe('entity review cards in the production review page', () => {
  it('shows method name, added notice and its explanation without writing or reading extra data', async () => {
    const { card } = await page(entity(), entity({ identifiers: { notice: 'product_info' } }))
    expect(card.get('h3').text()).toBe('合成方法名称')
    expect(card.text()).toContain('entity/E1')
    expect(card.text()).not.toContain('其他内容有更新')
    const field = card.get('[data-entity-field="/identifiers/notice"]')
    expect(field.text()).toContain('产品信息提示')
    expect(field.text()).toContain('新增')
    expect(field.get('[data-entity-before]').text()).toContain('未设置')
    expect(field.get('[data-entity-after]').text()).toContain('product_info')
    expect(field.text()).toContain('产品信息以已发布内容为准（合成提示）')
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo']])
    expect(vi.mocked(readReview).mock.calls).toEqual([['demo', 'c1']])
    expect(decidePoints).not.toHaveBeenCalled()
    vi.mocked(decidePoints).mockResolvedValue(pointResult(['entity/E1'], 'released'))
    await card.get('[data-point-approve]').trigger('click')
    await flushPromises()
    expect(vi.mocked(decidePoints).mock.calls).toEqual([['demo', 'c1', ['entity/E1'], 'approve', '核对无误']])
    expect(card.get('[data-point-state]').text()).toContain('已上线')
  })

  it('renders multiple product changes with labels supplied by the vocabulary', async () => {
    const old = entity({ entity_type: 'product', names: ['合成产品名称'],
      lifecycle: { sale_start: '2025-01-01', sale_end: null }, product_family: { key: 'f', display_name: '系列甲' },
      identifiers: { product_code: 'demo-before' } })
    const next = entity({ ...old.payload, lifecycle: { sale_start: '2025-01-01', sale_end: '2026-01-01' },
      product_family: { key: 'f', display_name: '系列乙' }, identifiers: { product_code: 'demo-after' } })
    const { card } = await page(old, next)
    expect(card.get('h3').text()).toBe('合成产品名称')
    expect(card.findAll('[data-entity-field]')).toHaveLength(3)
    const end = card.get('[data-entity-field="/lifecycle/sale_end"]')
    expect(end.text()).toContain('停售日期')
    expect(end.get('[data-entity-before]').text()).toContain('null')
    expect(end.get('[data-entity-after]').text()).toContain('2026-01-01')
    expect(card.get('[data-entity-field="/product_family/display_name"]').text()).toContain('产品线名称')
    expect(card.get('[data-entity-field="/identifiers/product_code"]').text()).toContain('登记标识')
    expect(card.text()).not.toContain('2025-01-01')
    vi.mocked(decidePoints).mockResolvedValue(pointResult(['entity/E1'], 'rejected'))
    await card.get('[data-point-reject]').trigger('click')
    expect(decidePoints).not.toHaveBeenCalled()
    await card.get('textarea').setValue('合成核对理由')
    await card.get('[data-point-confirm-reject]').trigger('click')
    await flushPromises()
    expect(vi.mocked(decidePoints).mock.calls[0]).toEqual(['demo', 'c1', ['entity/E1'], 'reject', '合成核对理由'])
  })

  it('falls back to ID and displays unknown fields and markup as text', async () => {
    const { card } = await page(entity(), entity({ names: [], future: { detail: '<b>合成文本</b>' } }))
    expect(card.get('h3').text()).toBe('E1')
    const field = card.get('[data-entity-field="/future/detail"]')
    expect(field.text()).toContain('/future/detail')
    expect(field.text()).toContain('<b>合成文本</b>')
    expect(field.find('b').exists()).toBe(false)
  })

  it('does not invent before values when the paired snapshot cannot be read', async () => {
    const { card } = await page(entity({ extra: 'not loaded' }), entity({ extra: 'candidate' }), { unavailable: true })
    const field = card.get('[data-entity-field="/extra"]')
    expect(field.get('[data-entity-before]').text()).toContain('不可读取')
    expect(field.text()).not.toContain('新增')
    expect(field.text()).not.toContain('not loaded')
    expect(card.get('[data-point-approve]').attributes('disabled')).toBeDefined()
    expect(decidePoints).not.toHaveBeenCalled()
  })

  it('shows removed fields for an entity removal and preserves its removal warning', async () => {
    const { card } = await page(entity({ identifiers: { notice: 'product_info' } }), null)
    expect(card.get('h3').text()).toBe('合成方法名称')
    expect(card.text()).toContain('删除这一项')
    const field = card.get('[data-entity-field="/identifiers/notice"]')
    expect(field.text()).toContain('删除')
    expect(field.get('[data-entity-before]').text()).toContain('旧提示说明')
    expect(field.get('[data-entity-after]').text()).toContain('未设置')
  })

  it('reports a metadata-only member update without inventing changed entity fields', async () => {
    const { card } = await page(entity(), { ...entity(), member_digest: 'b'.repeat(64) })
    expect(card.findAll('[data-entity-field]')).toHaveLength(0)
    expect(card.text()).toContain('实体字段无变化')
  })

  it('has the same nonempty entity vocabulary and action strings in all five languages', () => {
    const keys = ['id', 'type', 'names', 'aliases', 'classifications', 'owner', 'identifiers', 'notice',
      'productCode', 'filingNo', 'clauseNo', 'lifecycle', 'saleStart', 'saleEnd', 'sourceStatus',
      'basisCommit', 'basisDate', 'family', 'familyKey', 'familyName']
    for (const bundle of [zhCN, enUS, jaJP, koKR, ruRU]) {
      const review = bundle.enterpriseKnowledge.review as unknown as Record<string, unknown>
      const fields = review.entityFields as Record<string, unknown>
      expect(fields).toBeDefined()
      for (const key of keys) expect(typeof fields[key], key).toBe('string')
      const labels = review.entityChange as Record<string, unknown>
      for (const key of ['added', 'removed', 'changed', 'proposed', 'notSet', 'unavailable', 'unchanged']) {
        expect(typeof labels[key], key).toBe('string')
        expect(String(labels[key]).trim()).not.toBe('')
      }
    }
  })
})
