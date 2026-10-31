// @vitest-environment happy-dom
// RV5b acceptance (protected, written by Claude): administrators see the candidates waiting for a
// person and the decided ones (Spec docs/design/slices/RV5b-人工审核队列页面.md §3). RV6c replaced the
// whole-candidate decision with per-point decisions; those cases now live in reviewPointsPage.spec.ts
// (Spec docs/design/slices/RV6c-逐字段审核页面与首页工作台.md §4).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import enUS from '@/enterprise/i18n/locales/en-US'
import jaJP from '@/enterprise/i18n/locales/ja-JP'
import koKR from '@/enterprise/i18n/locales/ko-KR'
import ruRU from '@/enterprise/i18n/locales/ru-RU'
import routerSource from '@/enterprise/routes.ts?raw'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
  listConfirmations: vi.fn(),
  listReviews: vi.fn(),
  readReview: vi.fn(),
}))

import EnterpriseReviews from './EnterpriseReviews.vue'
import EnterpriseSpace from './EnterpriseSpace.vue'
import { EnterpriseError, listReviews, readRelease } from './enterpriseApi'
import { decidedItems, reviewItem } from './__tests__/reviewFixtures'
import { release } from './__tests__/s3eFixtures'
import { spotRelease } from './__tests__/spotCheckFixtures'

const views: ReturnType<typeof mount>[] = []
function page(spaceId = 'demo') {
  const view = mount(EnterpriseReviews, {
    attachTo: document.body,
    props: { spaceId },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub },
    },
  })
  views.push(view)
  return view
}

type View = ReturnType<typeof mount>
const ids = (view: View) => view.findAll('[data-review-item]').map(item => item.attributes('data-review-item'))

afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

describe('review queue', () => {
  it('lists the waiting candidates by product name and shows nothing internal', async () => {
    vi.mocked(listReviews).mockResolvedValue([
      reviewItem('cand-1'), reviewItem('cand-2', { subjects: ['C1'], members: 1, removals: 0 }),
    ])
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    expect(view.find('[role="status"]').exists()).toBe(true)
    await flushPromises()
    expect(vi.mocked(listReviews).mock.calls).toEqual([['demo', 'pending']])
    expect(vi.mocked(readRelease).mock.calls[0][0]).toBe('demo')
    expect(view.findAll('[data-review-tab]').map(tab => tab.text())).toEqual(['待审核', '已处理'])
    expect(ids(view)).toEqual(['cand-1', 'cand-2'])
    expect(view.get('[data-review-item="cand-1"] [data-review-subjects]').text()).toBe('甲医疗、乙医疗')
    expect(view.get('[data-review-item="cand-2"] [data-review-subjects]').text()).toBe('丙重疾')
    for (const internal of ['cand-1', 'svc-harness', 'rel-9']) expect(view.text()).not.toContain(internal)
    expect(view.find('[data-review-approve]').exists()).toBe(false)
  })

  it('falls back to the product ids when there is no release to name them', async () => {
    vi.mocked(listReviews).mockResolvedValue([reviewItem('cand-1')])
    vi.mocked(readRelease).mockRejectedValue(new EnterpriseError('RELEASE_NOT_FOUND', 404))
    const view = page()
    await flushPromises()
    expect(view.get('[data-review-subjects]').text()).toBe('M1、M2')
  })

  it('shows decided candidates with their outcome and reason, without actions', async () => {
    vi.mocked(listReviews).mockResolvedValueOnce([]).mockResolvedValueOnce(decidedItems())
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    await view.get('[data-review-tab="decided"]').trigger('click')
    await flushPromises()
    expect(vi.mocked(listReviews).mock.calls[1]).toEqual(['demo', 'decided'])
    const status = (id: string) => view.get(`[data-review-item="${id}"] [data-review-status]`).text()
    expect(status('cand-r')).toBe('已上线')
    expect(status('cand-a')).toBe('已批准，未能上线')
    expect(status('cand-x')).toBe('已拒绝')
    expect(view.get('[data-review-item="cand-x"] [data-review-decision-reason]').text()).toContain('取值与条款不符')
    expect(view.find('[data-review-approve]').exists() || view.find('[data-review-reject]').exists()).toBe(false)
    expect(view.text()).not.toContain('user:u-1')
  })

  it('shows an empty queue, and a failed one that can be retried', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    vi.mocked(listReviews).mockResolvedValueOnce([])
    const empty = page()
    await flushPromises()
    expect(empty.text()).toContain('没有待审核的修改')
    vi.mocked(listReviews)
      .mockRejectedValueOnce(new EnterpriseError('SERVICE_UNAVAILABLE', 503))
      .mockResolvedValueOnce([reviewItem('cand-1')])
    const failed = page()
    await flushPromises()
    expect(ids(failed)).toEqual([])
    await failed.get('[data-review-retry]').trigger('click')
    await flushPromises()
    expect(ids(failed)).toEqual(['cand-1'])
  })

  it('is reachable from the Space page through a registered route', async () => {
    vi.mocked(readRelease).mockResolvedValue(spotRelease())
    const view = mount(EnterpriseSpace, {
      props: { spaceId: 'demo' },
      global: {
        plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
        stubs: { RouterLink: RouterLinkStub },
      },
    })
    views.push(view)
    await flushPromises()
    const links = view.findAllComponents(RouterLinkStub).map(link => link.props('to'))
    expect(links).toContainEqual({ name: 'enterpriseReviews', params: { spaceId: 'demo' } })
    expect(routerSource).toMatch(new RegExp([
      'path: "enterprise/:spaceId/reviews",', 'name: "enterpriseReviews",',
      'component: \\(\\) => import\\("\\./EnterpriseReviews\\.vue"\\),',
    ].join('\\s*')))
  })

  it('words every review text in all five locales', () => {
    type Messages = { enterpriseKnowledge: { review?: Record<string, unknown> } }
    const flat = (value: unknown, prefix = ''): [string, unknown][] => Object.entries(value as Record<string, unknown>)
      .flatMap(([key, text]) => text && typeof text === 'object' ? flat(text, `${prefix}${key}.`) : [[`${prefix}${key}`, text]])
    const entries = (messages: unknown) => flat((messages as Messages).enterpriseKnowledge.review ?? {})
    const keys = entries(zhCN).map(([key]) => key).sort()
    expect(keys.length).toBeGreaterThan(0)
    for (const messages of [zhCN, enUS, jaJP, koKR, ruRU]) {
      expect(entries(messages).map(([key]) => key).sort()).toEqual(keys)
      expect(entries(messages).every(([, text]) => typeof text === 'string' && text.trim() !== '')).toBe(true)
    }
  })
})
