// @vitest-environment happy-dom
// Implementation-owned: real page, composable and API adapter; only HTTP is fake.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zhCN from '@/i18n/locales/zh-CN'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))
import { get, post } from '@/utils/request'
import EnterpriseReviews from './EnterpriseReviews.vue'
import { reviewDetail, reviewItem, reviewResult } from './__tests__/reviewFixtures'
import { release } from './__tests__/s3eFixtures'
const ok = (data: unknown) => ({ success: true, data, $httpStatus: 200 })
function deferred() {
  let resolve!: (value: any) => void, reject!: (error: unknown) => void
  const promise = new Promise<any>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const views: ReturnType<typeof mount>[] = []
function page() {
  const v = mount(EnterpriseReviews, { attachTo: document.body, props: { spaceId: 'demo' }, global: {
    plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })], stubs: { RouterLink: RouterLinkStub },
  } }); views.push(v); return v
}
function transport() {
  vi.mocked(get).mockImplementation(async (url: string) => url.includes('/releases/') ? ok(release())
    : url.includes('?status=') ? ok({ items: url.endsWith('pending') ? [reviewItem()] : [] }) : ok(reviewDetail()))
}
async function open(v: ReturnType<typeof page>) { await flushPromises(); await v.get('[data-review-open]').trigger('click'); await flushPromises() }
afterEach(() => { views.forEach(v => v.unmount()); views.length = 0; vi.resetAllMocks() })
describe('review HTTP lifecycle', () => {
  it('pairs the list and Release without resurrecting a stale tab', async () => {
    const list = deferred(), rel = deferred()
    vi.mocked(get).mockImplementation(async (url: string) => url.includes('/releases/') ? rel.promise : url.endsWith('pending') ? list.promise : ok({ items: [] }))
    const v = page(); await v.get('[data-review-tab="decided"]').trigger('click')
    rel.resolve(ok(release())); await flushPromises(); list.resolve(ok({ items: [reviewItem()] })); await flushPromises()
    expect(v.find('[data-review-item]').exists()).toBe(false)
    expect(v.get('[data-review-tab="decided"]').attributes('aria-selected')).toBe('true')
  })
  it.each([401, 403])('keeps a %s denial on its card', async status => {
    transport(); vi.mocked(post).mockRejectedValue({ status, code: 'RELEASE_ACCESS_DENIED' })
    const v = page(); await open(v); await v.get('[data-review-reason]').setValue('reviewed'); await v.get('[data-review-approve]').trigger('click'); await flushPromises()
    expect(v.find('[data-review-state]').exists()).toBe(false); expect(v.get('[role="alert"]').text()).toContain('RELEASE_ACCESS_DENIED')
  })
  it.each(['success', 'NEEDS_REBASE', 'CANDIDATE_DECIDED', 'CANDIDATE_INVALID'].flatMap(outcome =>
    ['space', 'tab'].map(change => ({ outcome, change }))))('drops late decision $outcome after $change change', async ({ outcome, change }) => {
    transport(); const pending = deferred(); vi.mocked(post).mockReturnValue(pending.promise)
    const v = page(); await open(v); await v.get('[data-review-reason]').setValue('reviewed'); await v.get('[data-review-approve]').trigger('click')
    if (change === 'space') await v.setProps({ spaceId: 'other' })
    else { await v.get('[data-review-tab="decided"]').trigger('click'); await flushPromises(); await v.get('[data-review-tab="pending"]').trigger('click') }
    await open(v); const field = v.get('[data-review-reason]'); (field.element as HTMLTextAreaElement).focus(); await field.setValue('other draft')
    const reads = vi.mocked(get).mock.calls.length
    if (outcome === 'success') pending.resolve(ok(reviewResult())); else pending.reject({ status: 409, code: outcome })
    await flushPromises(); expect(vi.mocked(get).mock.calls.length).toBe(reads); expect(document.activeElement).toBe(field.element)
    expect((field.element as HTMLTextAreaElement).value).toBe('other draft'); expect(v.find('[data-review-state]').exists()).toBe(false)
  })
  it.each(['NEEDS_REBASE', 'CANDIDATE_INVALID', 'CANDIDATE_DECIDED'].flatMap(code =>
    ['returns', 'fails'].map(outcome => ({ code, outcome }))))('drops a stale $code refresh that $outcome including focus', async ({ code, outcome }) => {
    transport(); const v = page(); await open(v); const pending = deferred(); let reads = 0
    vi.mocked(get).mockImplementation(async (url: string) => {
      if (url.includes('/releases/')) return ok(release())
      if (++reads === 1) return pending.promise
      return url.includes('?status=') ? ok({ items: url.endsWith('pending') ? [reviewItem()] : [] }) : ok(reviewDetail())
    })
    vi.mocked(post).mockRejectedValue({ status: 409, code }); await v.get('[data-review-reason]').setValue('reviewed'); await v.get('[data-review-approve]').trigger('click'); await flushPromises()
    await v.get('[data-review-tab="decided"]').trigger('click'); await flushPromises(); await v.get('[data-review-tab="pending"]').trigger('click'); await open(v)
    const field = v.get('[data-review-reason]'); (field.element as HTMLTextAreaElement).focus(); await field.setValue('new draft')
    if (outcome === 'fails') pending.reject({ status: 500, code: 'SERVICE_UNAVAILABLE' })
    else pending.resolve(code === 'CANDIDATE_DECIDED' ? ok({ items: [] }) : ok(reviewDetail('cand-1', { blocker: code })))
    await flushPromises()
    expect(document.activeElement).toBe(field.element); expect((field.element as HTMLTextAreaElement).value).toBe('new draft')
    expect(v.find('[data-review-blocker]').exists()).toBe(false); expect(v.find('[data-review-notice]').exists()).toBe(false)
  })
  it('does not invent a comparison against a different head', async () => {
    vi.mocked(get).mockImplementation(async (url: string) => url.includes('/releases/') ? ok(release())
      : url.includes('?status=') ? ok({ items: [reviewItem()] }) : ok(reviewDetail('cand-1', { head_release_id: 'new-head' })))
    const v = page(); await open(v); await v.get('[data-review-reason]').setValue('reviewed')
    expect(v.find('[data-review-change]').exists()).toBe(false); expect(v.get('[data-review-approve]').attributes('disabled')).toBeDefined()
    expect(v.get('[data-review-reject]').attributes('disabled')).toBeUndefined()
  })
  it('counts and sends Go-trimmed Unicode reasons; quotes never navigate', async () => {
    transport(); vi.mocked(post).mockResolvedValue(ok(reviewResult())); const v = page(); await open(v)
    expect(v.findAll('[data-review-quote] a, .ek-source').length).toBe(0)
    await v.get('[data-review-reason]').setValue('\uFEFF' + 'a'.repeat(2000)); expect(v.get('[data-review-approve]').attributes('disabled')).toBeDefined()
    await v.get('[data-review-reason]').setValue('\u0085' + '😀'.repeat(2000) + '\u0085'); expect(v.get('[data-review-approve]').attributes('disabled')).toBeUndefined()
    await v.get('[data-review-approve]').trigger('click'); await flushPromises()
    expect(vi.mocked(post).mock.calls[0]?.[1]).toEqual({ outcome: 'approve', reason: '😀'.repeat(2000) }); expect(document.activeElement).toBe(v.get('[data-review-state]').element)
  })
  it('keeps a denied candidate detail closed and retries only through the protected API', async () => {
    transport(); const v = page(); await flushPromises()
    vi.mocked(get).mockRejectedValueOnce({ status: 403, code: 'RELEASE_ACCESS_DENIED' })
    await v.get('[data-review-open]').trigger('click'); await flushPromises()
    expect(v.find('[data-review-approve]').exists()).toBe(false)
    expect(v.find('[data-review-quote]').exists()).toBe(false)
    expect(v.get('[role="alert"]').text()).toContain('RELEASE_ACCESS_DENIED')
    await v.get('[data-review-open]').trigger('click'); await flushPromises()
    expect(v.find('[data-review-change]').exists()).toBe(true)
  })
  it('rejects a different candidate response and a malformed success result', async () => {
    transport(); const v = page(); await flushPromises()
    vi.mocked(get).mockResolvedValueOnce(ok(reviewDetail('other-candidate')))
    await v.get('[data-review-open]').trigger('click'); await flushPromises()
    expect(v.get('[role="alert"]').text()).toContain('INVALID_RESPONSE')
    expect(v.find('[data-review-reason]').exists()).toBe(false)
    await v.get('[data-review-open]').trigger('click'); await flushPromises()
    vi.mocked(post).mockResolvedValueOnce(ok({ decision_id: 'd', status: 'released', epoch: null }))
    await v.get('[data-review-reason]').setValue('reviewed'); await v.get('[data-review-approve]').trigger('click'); await flushPromises()
    expect(v.get('[role="alert"]').text()).toContain('INVALID_RESPONSE')
    expect(v.find('[data-review-state]').exists()).toBe(false)
  })
  it('supports tab keyboard navigation with roving focus', async () => {
    transport(); const v = page(); await flushPromises()
    await v.get('[data-review-tab="pending"]').trigger('keydown', { key: 'End' }); await flushPromises()
    expect(document.activeElement).toBe(v.get('[data-review-tab="decided"]').element)
    expect(v.get('[data-review-tab="pending"]').attributes('tabindex')).toBe('-1')
    await v.get('[data-review-tab="decided"]').trigger('keydown', { key: 'Home' }); await flushPromises()
    expect(document.activeElement).toBe(v.get('[data-review-tab="pending"]').element)
  })

})
