// @vitest-environment happy-dom
// Implementation-owned: counts follow the lifetime of the Space/release visit.
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))
import { get } from '@/utils/request'
import EnterpriseSpace from './EnterpriseSpace.vue'
import { pointItem } from './__tests__/reviewPointFixtures'
import { release } from './__tests__/s3eFixtures'
import { deferred, ok } from './__tests__/pointLifecycleHarness'

const views: ReturnType<typeof mount>[] = []
function page() {
  const view = mount(EnterpriseSpace, { props: { spaceId: 'demo' }, global: {
    plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })], stubs: { RouterLink: RouterLinkStub },
  } }); views.push(view); return view
}
const count = (view: ReturnType<typeof page>) => view.get('[data-workbench-entry="reviews"] [data-workbench-count]').text()
function empty(url: string) {
  return url.includes('/releases/') ? ok(release()) : url.includes('/samples?') ? ok({ samples: [] }) : ok({ items: [] })
}
afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

it.each(['space', 'release', 'unmount'])('drops old count responses after %s changes', async change => {
  const old = deferred()
  vi.mocked(get).mockImplementation(async (url: string) => url.includes('/candidates?') ? old.promise : empty(url))
  const view = page(); await flushPromises()
  expect(count(view)).toBe('…')
  vi.mocked(get).mockImplementation(async (url: string) => empty(url))
  if (change === 'space') await view.setProps({ spaceId: 'other' })
  else if (change === 'release') await view.setProps({ releaseId: 'rel-pinned' })
  else { view.unmount(); views.splice(views.indexOf(view), 1) }
  await flushPromises()
  const calls = vi.mocked(get).mock.calls.length
  old.resolve(ok({ items: [pointItem('old', { pending_points: 7 })] })); await flushPromises()
  expect(vi.mocked(get).mock.calls).toHaveLength(calls)
  if (change !== 'unmount') expect(count(view)).toBe('无待办')
})

it('does not start counts from a stale release completion', async () => {
  const old = deferred()
  vi.mocked(get).mockImplementation(async (url: string) => url.includes('/spaces/demo/view/releases/') ? old.promise : empty(url))
  const view = page(); await view.setProps({ spaceId: 'other' }); await flushPromises()
  old.resolve(ok(release())); await flushPromises()
  expect(vi.mocked(get).mock.calls.filter(([url]) => url.includes('/spaces/demo/') && !url.includes('/releases/'))).toHaveLength(0)
})

it.each([undefined, null, '7', -1, 1.5, Number.MAX_SAFE_INTEGER + 1])('keeps the review link without a malformed count %s', async pending => {
  vi.mocked(get).mockImplementation(async (url: string) => url.includes('/candidates?')
    ? ok({ items: [{ ...pointItem(), pending_points: pending }] }) : empty(url))
  const view = page(); await flushPromises()
  const entry = view.get('[data-workbench-entry="reviews"]')
  expect(entry.find('[data-workbench-count]').exists()).toBe(false)
})

it('clears old counts while the replacement release is pending and after it fails', async () => {
  vi.mocked(get).mockImplementation(async (url: string) => empty(url))
  const view = page(); await flushPromises(); expect(count(view)).toBe('无待办')
  const pending = deferred()
  vi.mocked(get).mockImplementation(() => pending.promise)
  await view.setProps({ spaceId: 'other' })
  expect(view.find('[data-space-workbench]').exists()).toBe(false)
  pending.reject({ code: 'SERVICE_UNAVAILABLE', status: 503 }); await flushPromises()
  expect(view.find('[data-space-workbench]').exists()).toBe(false)
})

it.each([
  { candidate_id: '' }, { status: 'released' }, { point_count: 1 }, { point_count: null },
])('does not count an inconsistent review summary %j', async extra => {
  vi.mocked(get).mockImplementation(async (url: string) => url.includes('/candidates?')
    ? ok({ items: [{ ...pointItem(), ...extra }] }) : empty(url))
  const view = page(); await flushPromises()
  expect(view.get('[data-workbench-entry="reviews"]').find('[data-workbench-count]').exists()).toBe(false)
})
