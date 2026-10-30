// @vitest-environment happy-dom
// RV6c acceptance (protected, written by Claude): the review page groups the waiting candidates by
// product, opens the first one, and lets an administrator approve or reject each review point next
// to it, the unknown ones as a group, or the rest of a product at once
// (Spec docs/design/slices/RV6c-逐字段审核页面与首页工作台.md §1).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import enUS from '@/enterprise/i18n/locales/en-US'
import jaJP from '@/enterprise/i18n/locales/ja-JP'
import koKR from '@/enterprise/i18n/locales/ko-KR'
import ruRU from '@/enterprise/i18n/locales/ru-RU'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
  listReviews: vi.fn(),
  readReview: vi.fn(),
  decidePoints: vi.fn(),
}))

import EnterpriseReviews from './EnterpriseReviews.vue'
import { decidePoints, EnterpriseError, listReviews, readRelease, readReview, type PointResult, type ReviewDetail } from './enterpriseApi'
import {
  CARD_SLUGS, PENDING_SLUGS, UNKNOWN_SLUGS, point, pointDetail, pointItem, pointResult, rejected, released,
} from './__tests__/reviewPointFixtures'
import { release } from './__tests__/s3eFixtures'

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
type Wrapper = ReturnType<View['get']>
const disabled = (element: Wrapper) => element.attributes('disabled') !== undefined
// Cards of pending points with a value: not the unknown group's members, not the decided list.
const cards = (scope: View | Wrapper) => scope.findAll('[data-point]')
  .filter(card => !card.element.closest('[data-point-unknown-group]') && !card.element.closest('[data-point-decided]'))
  .map(card => card.attributes('data-point')!).sort()
const sorted = (slugs: unknown) => [...(slugs as string[])].sort()

async function opened(detail: ReviewDetail = pointDetail()) {
  vi.mocked(listReviews).mockResolvedValue([
    pointItem('cand-1'), pointItem('cand-2', { subjects: ['C1'], members: 2, removals: 0, point_count: 2, pending_points: 2 }),
  ])
  vi.mocked(readRelease).mockResolvedValue(release())
  vi.mocked(readReview).mockResolvedValue(detail)
  const view = page()
  await flushPromises()
  return { view, product: view.get('[data-review-item="cand-1"]') }
}

afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

describe('review points by product', () => {
  it('opens the first product with one card per point and leaves the others closed', async () => {
    const { view, product } = await opened()
    expect(vi.mocked(readReview).mock.calls).toEqual([['demo', 'cand-1']])
    expect(product.get('[data-review-subjects]').text()).toBe('甲医疗、乙医疗')
    expect(product.get('[data-review-progress]').text()).toMatch(/待审\s*7\s*\/\s*共\s*7\s*项/)
    const other = view.get('[data-review-item="cand-2"]')
    expect(other.find('[data-point]').exists()).toBe(false)
    expect(other.find('[data-review-open]').exists()).toBe(true)
    expect(other.get('[data-review-subjects]').text()).toBe('丙重疾')

    expect(cards(product)).toEqual(CARD_SLUGS)
    const changed = product.get('[data-point="M1/waiting_period"]')
    expect(changed.text()).toContain('甲医疗')
    expect(changed.text()).toContain('等待期')
    expect(changed.get('[data-point-before]').text()).toContain('90日。')
    expect(changed.get('[data-point-after]').text()).toContain('180日。')
    expect(changed.findAll('[data-point-quote]').map(quote => quote.text())).toEqual(['等待期为180日。'])
    expect(changed.find('[data-point-approve]').exists() && changed.find('[data-point-reject]').exists()).toBe(true)
    const filled = product.get('[data-point="M2/waiting_period"]')
    expect(filled.text()).toContain('乙医疗')
    expect(filled.get('[data-point-after]').text()).toContain('30日。')
    expect(filled.find('[data-point-before]').exists() && filled.get('[data-point-before]').text().includes('30日')).toBe(false)
    const removal = product.get('[data-point="M1/premium_grace_period"]')
    expect(removal.text()).toContain('删除这一项')
    expect(removal.get('[data-point-before]').text()).toContain('60日。')
    expect(removal.find('[data-point-after]').exists() && removal.get('[data-point-after]').text().includes('60日')).toBe(false)
    const content = product.get('[data-point="entity/M1"]')
    expect(content.text()).toContain('其他内容有更新')
    expect(content.text()).toContain('entity/M1')
    expect(content.text()).not.toContain('classification_labels')

    const unknown = product.get('[data-point-unknown-group]')
    expect(unknown.text()).toContain('犹豫期')
    expect(unknown.text()).toContain('宽限期')
    for (const internal of ['cand-1', 'svc-harness', 'rel-9']) expect(view.text()).not.toContain(internal)
  })

  it('approves one point with the default reason and turns its card into a status line', async () => {
    const { product } = await opened()
    const pending = deferred<PointResult>()
    vi.mocked(decidePoints).mockReturnValue(pending.promise)
    await product.get('[data-point="M1/waiting_period"] [data-point-approve]').trigger('click')
    expect(vi.mocked(decidePoints).mock.calls).toEqual([['demo', 'cand-1', ['M1/waiting_period'], 'approve', '核对无误']])
    expect(disabled(product.get('[data-point="M1/waiting_period"] [data-point-approve]'))).toBe(true)
    pending.resolve(pointResult(['M1/waiting_period'], 'released'))
    await flushPromises()
    const card = product.get('[data-point="M1/waiting_period"]')
    const state = card.get('[data-point-state]')
    expect(state.attributes('role')).toBe('status')
    expect(state.text()).toContain('已上线')
    expect(state.text()).toContain('16')
    expect(document.activeElement).toBe(state.element)
    expect(card.find('[data-point-approve]').exists() || card.find('[data-point-reject]').exists()).toBe(false)
    expect(product.get('[data-review-progress]').text()).toMatch(/待审\s*6\s*\/\s*共\s*7\s*项/)
    expect(vi.mocked(listReviews)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(readReview)).toHaveBeenCalledTimes(1)
  })

  it('sends a reason the reviewer chose to write for an approval', async () => {
    const { product } = await opened()
    vi.mocked(decidePoints).mockResolvedValue(pointResult(['M2/waiting_period'], 'released'))
    const card = product.get('[data-point="M2/waiting_period"]')
    const write = card.findAll('button').find(button => button.text() === '填写理由')
    expect(write).toBeDefined()
    await write!.trigger('click')
    await card.get('textarea').setValue('  已与条款第五条核对 ')
    await card.get('[data-point-approve]').trigger('click')
    await flushPromises()
    expect(vi.mocked(decidePoints).mock.calls[0]).toEqual(['demo', 'cand-1', ['M2/waiting_period'], 'approve', '已与条款第五条核对'])
  })

  it('asks for a reason before a rejection is sent', async () => {
    const { product } = await opened()
    vi.mocked(decidePoints).mockResolvedValue(pointResult(['M2/waiting_period'], 'rejected'))
    const card = product.get('[data-point="M2/waiting_period"]')
    await card.get('[data-point-reject]').trigger('click')
    expect(vi.mocked(decidePoints)).not.toHaveBeenCalled()
    const confirm = card.get('[data-point-confirm-reject]')
    expect(disabled(confirm)).toBe(true)
    await card.get('textarea').setValue('   ')
    expect(disabled(card.get('[data-point-confirm-reject]'))).toBe(true)
    await card.get('textarea').setValue('长'.repeat(2001))
    expect(disabled(card.get('[data-point-confirm-reject]'))).toBe(true)
    await card.get('textarea').setValue(' 取值与条款不符 ')
    expect(disabled(card.get('[data-point-confirm-reject]'))).toBe(false)
    await card.get('[data-point-confirm-reject]').trigger('click')
    await flushPromises()
    expect(vi.mocked(decidePoints).mock.calls).toEqual([['demo', 'cand-1', ['M2/waiting_period'], 'reject', '取值与条款不符']])
    expect(product.get('[data-point="M2/waiting_period"] [data-point-state]').text()).toContain('已拒绝')
  })

  it('decides the unknown fields as one group', async () => {
    const { product } = await opened()
    vi.mocked(decidePoints).mockResolvedValue(pointResult(UNKNOWN_SLUGS, 'released'))
    const group = product.get('[data-point-unknown-group]')
    await group.get('[data-unknown-reject]').trigger('click')
    expect(vi.mocked(decidePoints)).not.toHaveBeenCalled()
    expect(disabled(group.get('[data-point-confirm-reject]'))).toBe(true)
    await group.get('[data-unknown-approve]').trigger('click')
    await flushPromises()
    expect(vi.mocked(decidePoints)).toHaveBeenCalledTimes(1)
    const [space, candidate, slugs, outcome, reason] = vi.mocked(decidePoints).mock.calls[0]
    expect([space, candidate, sorted(slugs), outcome, reason]).toEqual(['demo', 'cand-1', UNKNOWN_SLUGS, 'approve', '核对无误'])
    expect(product.get('[data-review-progress]').text()).toMatch(/待审\s*5\s*\/\s*共\s*7\s*项/)
  })

  it('approves the rest only after a confirmation and leaves the blocked point out', async () => {
    const { product } = await opened()
    vi.mocked(decidePoints).mockResolvedValue(pointResult(PENDING_SLUGS.filter(slug => slug !== 'M2/cooling_off_period'), 'released'))
    const rest = product.get('[data-review-approve-rest]')
    expect(rest.text()).toContain('批准其余 6 项')
    expect(product.text()).toContain('另有 1 项需先处理冲突')
    await rest.trigger('click')
    expect(vi.mocked(decidePoints)).not.toHaveBeenCalled()
    expect(product.get('[data-review-approve-rest]').text()).toContain('确认批准其余 6 项')
    await product.get('[data-review-approve-rest]').trigger('click')
    await flushPromises()
    expect(vi.mocked(decidePoints)).toHaveBeenCalledTimes(1)
    const [, , slugs, outcome, reason] = vi.mocked(decidePoints).mock.calls[0]
    expect(sorted(slugs)).toEqual(PENDING_SLUGS.filter(slug => slug !== 'M2/cooling_off_period'))
    expect([outcome, reason]).toEqual(['approve', '核对无误'])
    expect(product.get('[data-point="M2/cooling_off_period"]').find('[data-point-reject]').exists()).toBe(true)
  })

  it('lets a blocked point only be rejected', async () => {
    const { product } = await opened()
    const blocked = product.get('[data-point="M2/cooling_off_period"]')
    expect(blocked.text()).toContain('当前版本已改过这一项，需要重新编译后再审')
    expect(disabled(blocked.get('[data-point-approve]'))).toBe(true)
    expect(disabled(blocked.get('[data-point-reject]'))).toBe(false)
  })

  it('reads the product again when a point was decided elsewhere', async () => {
    const { view, product } = await opened()
    vi.mocked(decidePoints).mockRejectedValue(new EnterpriseError('MEMBER_DECIDED', 409))
    const after = pointDetail('cand-1', PENDING_SLUGS.map(slug => slug === 'M1/waiting_period' ? rejected(slug) : point(slug)))
    vi.mocked(readReview).mockResolvedValueOnce(after)
    await product.get('[data-point="M1/waiting_period"] [data-point-approve]').trigger('click')
    await flushPromises()
    expect(vi.mocked(readReview).mock.calls).toEqual([['demo', 'cand-1'], ['demo', 'cand-1']])
    expect(vi.mocked(listReviews)).toHaveBeenCalledTimes(1)
    expect(view.text()).toContain('有字段已由他人处理')
    expect(cards(view.get('[data-review-item="cand-1"]'))).toEqual(CARD_SLUGS.filter(slug => slug !== 'M1/waiting_period'))
    expect(view.get('[data-review-item="cand-1"] [data-review-progress]').text()).toMatch(/待审\s*6\s*\/\s*共\s*7\s*项/)
  })

  it('reads the product again when the Head changed the point', async () => {
    const { view, product } = await opened()
    vi.mocked(decidePoints).mockRejectedValue(new EnterpriseError('NEEDS_REBASE', 409))
    vi.mocked(readReview).mockResolvedValueOnce(pointDetail('cand-1', PENDING_SLUGS.map(slug =>
      point(slug, slug === 'M1/waiting_period' ? { blocker: 'NEEDS_REBASE' } : {}))))
    await product.get('[data-point="M1/waiting_period"] [data-point-approve]').trigger('click')
    await flushPromises()
    const card = view.get('[data-review-item="cand-1"] [data-point="M1/waiting_period"]')
    expect(card.text()).toContain('当前版本已改过这一项')
    expect(disabled(card.get('[data-point-approve]'))).toBe(true)
    expect(card.find('[data-point-state]').exists()).toBe(false)
  })

  it('keeps other failures on the card so the decision can be retried', async () => {
    const { product } = await opened()
    vi.mocked(decidePoints).mockRejectedValueOnce(new EnterpriseError('SERVICE_UNAVAILABLE', 503))
    await product.get('[data-point="M1/waiting_period"] [data-point-approve]').trigger('click')
    await flushPromises()
    const card = product.get('[data-point="M1/waiting_period"]')
    expect(card.text()).toContain('SERVICE_UNAVAILABLE')
    expect(disabled(card.get('[data-point-approve]'))).toBe(false)
    vi.mocked(decidePoints).mockResolvedValueOnce(pointResult(['M1/waiting_period'], 'released'))
    await card.get('[data-point-approve]').trigger('click')
    await flushPromises()
    expect(product.get('[data-point="M1/waiting_period"] [data-point-state]').text()).toContain('已上线')
  })

  it('says when a product has nothing left to decide', async () => {
    const points = PENDING_SLUGS.map(slug => slug === 'M2/waiting_period' ? point(slug) : released(slug))
    const { product } = await opened(pointDetail('cand-1', points))
    expect(cards(product)).toEqual(['M2/waiting_period'])
    expect(product.find('[data-point-decided]').exists()).toBe(true)
    vi.mocked(decidePoints).mockResolvedValue(pointResult(['M2/waiting_period'], 'rejected', { status: 'released' }))
    await product.get('[data-point="M2/waiting_period"] [data-point-reject]').trigger('click')
    await product.get('[data-point="M2/waiting_period"] textarea').setValue('不对')
    await product.get('[data-point="M2/waiting_period"] [data-point-confirm-reject]').trigger('click')
    await flushPromises()
    expect(product.text()).toContain('本产品已全部处理')
    expect(product.find('[data-review-approve-rest]').exists()
      && !disabled(product.get('[data-review-approve-rest]'))).toBe(false)
  })

  it('shows a failed product read with a retry', async () => {
    vi.mocked(listReviews).mockResolvedValue([pointItem('cand-1')])
    vi.mocked(readRelease).mockResolvedValue(release())
    vi.mocked(readReview).mockRejectedValueOnce(new EnterpriseError('SERVICE_UNAVAILABLE', 503)).mockResolvedValueOnce(pointDetail())
    const view = page()
    await flushPromises()
    const product = view.get('[data-review-item="cand-1"]')
    expect(product.get('[role="alert"]').text()).toContain('SERVICE_UNAVAILABLE')
    expect(product.find('[data-point]').exists()).toBe(false)
    const retry = product.findAll('button').find(button => button.text() === '重试')
    expect(retry).toBeDefined()
    await retry!.trigger('click')
    await flushPromises()
    expect(cards(view.get('[data-review-item="cand-1"]'))).toEqual(CARD_SLUGS)
  })
})

describe('decided candidates and tab changes', () => {
  it('lists decided products with their status and opens their points without actions', async () => {
    const decidedItem = pointItem('cand-d', { status: 'released', release_id: 'rel-10', pending_points: 0 })
    vi.mocked(listReviews).mockResolvedValueOnce([]).mockResolvedValueOnce([decidedItem])
    vi.mocked(readRelease).mockResolvedValue(release())
    vi.mocked(readReview).mockResolvedValue(pointDetail('cand-d', PENDING_SLUGS.map(slug =>
      slug === 'M2/waiting_period' ? rejected(slug, '取值与条款不符') : released(slug, '核对无误')), { status: 'released', release_id: 'rel-10' }))
    const view = page()
    await flushPromises()
    await view.get('[data-review-tab="decided"]').trigger('click')
    await flushPromises()
    expect(vi.mocked(listReviews).mock.calls[1]).toEqual(['demo', 'decided'])
    const item = view.get('[data-review-item="cand-d"]')
    expect(item.text()).toContain('已上线')
    expect(item.text()).toMatch(/共\s*7\s*项/)
    expect(vi.mocked(readReview)).not.toHaveBeenCalled()
    await item.get('[data-review-open]').trigger('click')
    await flushPromises()
    expect(vi.mocked(readReview).mock.calls).toEqual([['demo', 'cand-d']])
    expect(view.text()).toContain('取值与条款不符')
    for (const action of ['[data-point-approve]', '[data-point-reject]', '[data-unknown-approve]', '[data-review-approve-rest]']) {
      expect(view.find(action).exists()).toBe(false)
    }
    expect(view.text()).not.toContain('user:u-1')
  })

  it('drops a product read that arrives after the tab was switched', async () => {
    const decidedItem = pointItem('cand-d', { status: 'released', release_id: 'rel-10', pending_points: 0 })
    vi.mocked(listReviews).mockResolvedValueOnce([pointItem('cand-1')]).mockResolvedValueOnce([decidedItem])
    vi.mocked(readRelease).mockResolvedValue(release())
    const late = deferred<ReviewDetail>()
    vi.mocked(readReview).mockReturnValue(late.promise)
    const view = page()
    await flushPromises()
    await view.get('[data-review-tab="decided"]').trigger('click')
    await flushPromises()
    late.resolve(pointDetail())
    await flushPromises()
    expect(view.find('[data-point]').exists()).toBe(false)
    expect(view.findAll('[data-review-item]').map(item => item.attributes('data-review-item'))).toEqual(['cand-d'])
  })

  it('words the default reason and every review text in all five locales', () => {
    type Messages = { enterpriseKnowledge: Record<string, unknown> }
    const flat = (value: unknown, prefix = ''): [string, unknown][] => Object.entries(value as Record<string, unknown>)
      .flatMap(([key, text]) => text && typeof text === 'object' ? flat(text, `${prefix}${key}.`) : [[`${prefix}${key}`, text]])
    const entries = (messages: unknown) => flat((messages as Messages).enterpriseKnowledge)
    expect((zhCN as unknown as Messages).enterpriseKnowledge.review).toMatchObject({ defaultReason: '核对无误' })
    const keys = entries(zhCN).map(([key]) => key).sort()
    for (const messages of [zhCN, enUS, jaJP, koKR, ruRU]) {
      expect(entries(messages).map(([key]) => key).sort()).toEqual(keys)
      expect(entries(messages).every(([, text]) => typeof text === 'string' && text.trim() !== '')).toBe(true)
    }
  })
})
