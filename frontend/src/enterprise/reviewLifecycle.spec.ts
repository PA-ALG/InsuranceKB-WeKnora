// @vitest-environment happy-dom
// Implementation-owned: real page, composable and API adapter; only HTTP is fake.
// RV6c (Claude, RED commit): the whole-candidate decision cases were removed with that decision;
// the per-point lifecycle is the implementer's to cover again.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zhCN from '@/i18n/locales/zh-CN'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))
import { get } from '@/utils/request'
import EnterpriseReviews from './EnterpriseReviews.vue'
import { reviewDetail, reviewItem } from './__tests__/reviewFixtures'
import { release } from './__tests__/s3eFixtures'
const ok = (data: unknown) => ({ success: true, data, $httpStatus: 200 })
function deferred() {
  let resolve!: (value: any) => void
  const promise = new Promise<any>(yes => { resolve = yes })
  return { promise, resolve }
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
  it('supports tab keyboard navigation with roving focus', async () => {
    transport(); const v = page(); await flushPromises()
    await v.get('[data-review-tab="pending"]').trigger('keydown', { key: 'End' }); await flushPromises()
    expect(document.activeElement).toBe(v.get('[data-review-tab="decided"]').element)
    expect(v.get('[data-review-tab="pending"]').attributes('tabindex')).toBe('-1')
    await v.get('[data-review-tab="decided"]').trigger('keydown', { key: 'Home' }); await flushPromises()
    expect(document.activeElement).toBe(v.get('[data-review-tab="pending"]').element)
  })

})
