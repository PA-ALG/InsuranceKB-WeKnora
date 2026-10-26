// @vitest-environment happy-dom
// RV5b acceptance (protected, written by Claude): administrators see the candidates waiting for a
// person with each field's old and new value and its quotes, and approve or reject them with a
// reason (Spec docs/design/slices/RV5b-人工审核队列页面.md §3).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/i18n/locales/zh-CN'
import enUS from '@/i18n/locales/en-US'
import jaJP from '@/i18n/locales/ja-JP'
import koKR from '@/i18n/locales/ko-KR'
import ruRU from '@/i18n/locales/ru-RU'
import routerSource from '@/router/index.ts?raw'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
  listConfirmations: vi.fn(),
  listReviews: vi.fn(),
  readReview: vi.fn(),
  decideReview: vi.fn(),
}))

import EnterpriseReviews from './EnterpriseReviews.vue'
import EnterpriseSpace from './EnterpriseSpace.vue'
import {
  decideReview, EnterpriseError, listReviews, readRelease, readReview,
  type ReviewDetail, type ReviewResult,
} from './enterpriseApi'
import { decidedItems, reviewDetail, reviewItem, reviewResult } from './__tests__/reviewFixtures'
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

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

type View = ReturnType<typeof mount>
const ids = (view: View) => view.findAll('[data-review-item]').map(item => item.attributes('data-review-item'))
const disabled = (element: { attributes: (name: string) => string | undefined }) => element.attributes('disabled') !== undefined
const changes = (view: View) => view.findAll('[data-review-change]').map(row => row.attributes('data-review-change')).sort()

async function opened(detail: ReviewDetail = reviewDetail()) {
  vi.mocked(listReviews).mockResolvedValue([reviewItem('cand-1')])
  vi.mocked(readRelease).mockResolvedValue(release())
  vi.mocked(readReview).mockResolvedValue(detail)
  const view = page()
  await flushPromises()
  await view.get('[data-review-item="cand-1"] [data-review-open]').trigger('click')
  await flushPromises()
  return { view, card: view.get('[data-review-item="cand-1"]') }
}

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

  it('shows each field\'s old and new value with the candidate\'s quotes', async () => {
    const { view, card } = await opened()
    expect(vi.mocked(readReview).mock.calls).toEqual([['demo', 'cand-1']])
    expect(changes(view)).toEqual(['M1/premium_grace_period', 'M1/waiting_period', 'M2/waiting_period'])
    const changed = card.get('[data-review-change="M1/waiting_period"]')
    expect(changed.text()).toContain('甲医疗')
    expect(changed.text()).toContain('等待期')
    expect(changed.get('[data-review-before]').text()).toContain('90日。')
    expect(changed.get('[data-review-after]').text()).toContain('180日。')
    expect(changed.findAll('[data-review-quote]').map(quote => quote.text())).toEqual(['等待期为180日。'])
    const filled = card.get('[data-review-change="M2/waiting_period"]')
    expect(filled.text()).toContain('乙医疗')
    expect(filled.get('[data-review-before]').text()).not.toContain('30日')
    expect(filled.get('[data-review-after]').text()).toContain('30日。')
    expect(filled.findAll('[data-review-quote]').map(quote => quote.text())).toEqual(['本合同的等待期为30日。'])
    const removed = card.get('[data-review-change="M1/premium_grace_period"]')
    expect(removed.text()).toContain('宽限期')
    expect(removed.get('[data-review-before]').text()).toContain('60日。')
    expect(removed.find('[data-review-after]').exists() && removed.get('[data-review-after]').text().includes('60日')).toBe(false)
    expect(card.find('[data-review-blocker]').exists()).toBe(false)
    expect(disabled(card.get('[data-review-approve]'))).toBe(true)
    expect(disabled(card.get('[data-review-reject]'))).toBe(true)
  })

  it('approves with the trimmed reason and shows the release it became', async () => {
    const { card } = await opened()
    const pending = deferred<ReviewResult>()
    vi.mocked(decideReview).mockReturnValue(pending.promise)
    const approve = card.get('[data-review-approve]')
    expect(approve.text()).toBe('批准上线')
    await card.get('[data-review-reason]').setValue('  核对无误  ')
    expect(disabled(approve)).toBe(false)
    await approve.trigger('click')
    expect(vi.mocked(decideReview).mock.calls).toEqual([['demo', 'cand-1', 'approve', '核对无误']])
    expect(disabled(card.get('[data-review-approve]'))).toBe(true)
    expect(disabled(card.get('[data-review-reject]'))).toBe(true)
    pending.resolve(reviewResult({ status: 'released', epoch: 16 }))
    await flushPromises()
    expect(card.get('[data-review-state]').text()).toContain('已上线（第 16 版）')
    expect(card.find('[data-review-approve]').exists()).toBe(false)
    expect(card.find('[data-review-reject]').exists()).toBe(false)
  })

  it('rejects with a reason and publishes nothing', async () => {
    const { card } = await opened()
    vi.mocked(decideReview).mockResolvedValue(reviewResult({ status: 'rejected', release_id: null, epoch: null }))
    expect(card.get('[data-review-reject]').text()).toBe('拒绝')
    await card.get('[data-review-reason]').setValue('取值与条款不符')
    await card.get('[data-review-reject]').trigger('click')
    await flushPromises()
    expect(vi.mocked(decideReview).mock.calls).toEqual([['demo', 'cand-1', 'reject', '取值与条款不符']])
    expect(card.get('[data-review-state]').text()).toContain('已拒绝')
  })

  it.each([
    ['NEEDS_REBASE', '内容已过期：当前版本改过这些字段，需要重新编译后再审核'],
    ['CANDIDATE_INVALID', '这份修改无法合并到当前版本，需要重新编译'],
    ['SOURCE_UNAVAILABLE', '这份修改暂时无法上线'],
  ])('a candidate blocked by %s can only be rejected', async (blocker, message) => {
    const { card } = await opened(reviewDetail('cand-1', { blocker }))
    const shown = card.get('[data-review-blocker]').text()
    expect(shown).toContain(message)
    if (blocker === 'SOURCE_UNAVAILABLE') expect(shown).toContain('SOURCE_UNAVAILABLE')
    await card.get('[data-review-reason]').setValue('需要重新编译')
    expect(disabled(card.get('[data-review-approve]'))).toBe(true)
    expect(disabled(card.get('[data-review-reject]'))).toBe(false)
  })

  it('reads the candidate again when the approval finds it stale', async () => {
    const { card } = await opened()
    vi.mocked(readReview).mockResolvedValueOnce(reviewDetail('cand-1', { blocker: 'NEEDS_REBASE' }))
    vi.mocked(decideReview).mockRejectedValue(new EnterpriseError('NEEDS_REBASE', 409))
    await card.get('[data-review-reason]').setValue('核对无误')
    await card.get('[data-review-approve]').trigger('click')
    await flushPromises()
    expect(vi.mocked(readReview)).toHaveBeenCalledTimes(2)
    expect(card.get('[data-review-blocker]').text()).toContain('内容已过期')
    expect(disabled(card.get('[data-review-approve]'))).toBe(true)
    expect(card.find('[data-review-state]').exists()).toBe(false)
  })

  it('reloads the list with a notice when someone else decided first', async () => {
    const { view, card } = await opened()
    vi.mocked(listReviews).mockResolvedValue([])
    vi.mocked(decideReview).mockRejectedValue(new EnterpriseError('CANDIDATE_DECIDED', 409))
    await card.get('[data-review-reason]').setValue('核对无误')
    await card.get('[data-review-approve]').trigger('click')
    await flushPromises()
    expect(vi.mocked(listReviews)).toHaveBeenCalledTimes(2)
    expect(view.get('[data-review-notice]').text()).toContain('这份修改已由其他人处理')
    expect(ids(view)).toEqual([])
  })

  it('keeps other failures on the card so the decision can be retried', async () => {
    const { card } = await opened()
    vi.mocked(decideReview).mockRejectedValueOnce(new EnterpriseError('SERVICE_UNAVAILABLE', 503))
    await card.get('[data-review-reason]').setValue('核对无误')
    await card.get('[data-review-approve]').trigger('click')
    await flushPromises()
    expect(card.text()).toContain('SERVICE_UNAVAILABLE')
    expect(disabled(card.get('[data-review-approve]'))).toBe(false)
    vi.mocked(decideReview).mockResolvedValueOnce(reviewResult())
    await card.get('[data-review-approve]').trigger('click')
    await flushPromises()
    expect(card.get('[data-review-state]').text()).toContain('已上线')
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

  it('counts the reason the way the server does', async () => {
    const { card } = await opened()
    await card.get('[data-review-reason]').setValue('长'.repeat(2001))
    expect(card.text()).toContain('2001 / 2000 字')
    expect(disabled(card.get('[data-review-approve]'))).toBe(true)
    expect(disabled(card.get('[data-review-reject]'))).toBe(true)
    await card.get('[data-review-reason]').setValue(` ${'长'.repeat(2000)}\n`)
    expect(card.text()).toContain('2000 / 2000 字')
    expect(disabled(card.get('[data-review-approve]'))).toBe(false)
    await card.get('[data-review-reason]').setValue('   ')
    expect(disabled(card.get('[data-review-reject]'))).toBe(true)
  })

  it('drops a candidate that arrives after the tab was switched', async () => {
    vi.mocked(listReviews).mockResolvedValueOnce([reviewItem('cand-1')]).mockResolvedValueOnce(decidedItems())
    vi.mocked(readRelease).mockResolvedValue(release())
    const late = deferred<ReviewDetail>()
    vi.mocked(readReview).mockReturnValue(late.promise)
    const view = page()
    await flushPromises()
    await view.get('[data-review-item="cand-1"] [data-review-open]').trigger('click')
    await view.get('[data-review-tab="decided"]').trigger('click')
    await flushPromises()
    late.resolve(reviewDetail())
    await flushPromises()
    expect(view.findAll('[data-review-change]')).toHaveLength(0)
    expect(ids(view)).toEqual(['cand-r', 'cand-a', 'cand-x'])
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
      'component: \\(\\) => import\\("\\.\\./enterprise/EnterpriseReviews\\.vue"\\),',
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
