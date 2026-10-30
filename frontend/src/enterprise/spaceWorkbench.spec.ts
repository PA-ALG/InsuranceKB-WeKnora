// @vitest-environment happy-dom
// RV6c acceptance (protected, written by Claude): the Space home keeps knowledge reading apart from
// a 工作台 that links to the review queue, the confirmations and the spot checks with their open
// counts; counts never delay the home, also show on a Space that has never published, and an entry
// the user may not open is hidden (Spec docs/design/slices/RV6c-逐字段审核页面与首页工作台.md §2).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
  listReviews: vi.fn(),
  listConfirmations: vi.fn(),
  listSamples: vi.fn(),
}))

import EnterpriseSpace from './EnterpriseSpace.vue'
import {
  EnterpriseError, listConfirmations, listReviews, listSamples, readRelease,
  type ConfirmationItem, type ReviewItem, type SpotSample,
} from './enterpriseApi'
import { confirmationItem } from './__tests__/confirmationFixtures'
import { pointItem } from './__tests__/reviewPointFixtures'
import { release } from './__tests__/s3eFixtures'
import { spotSample } from './__tests__/spotCheckFixtures'

const views: ReturnType<typeof mount>[] = []
function home() {
  const view = mount(EnterpriseSpace, {
    attachTo: document.body,
    props: { spaceId: 'demo' },
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
const ROUTES = { reviews: 'enterpriseReviews', confirmations: 'enterpriseConfirmations', spotchecks: 'enterpriseSpotChecks' }
const entry = (view: View, key: string) => view.find(`[data-space-workbench] [data-workbench-entry="${key}"]`)
const count = (view: View, key: string) => entry(view, key).find('[data-workbench-count]')

function counts(reviews: ReviewItem[] | Error, confirmations: ConfirmationItem[] | Error, samples: SpotSample[] | Error) {
  const settle = <T>(value: T | Error) => value instanceof Error ? Promise.reject(value) : Promise.resolve(value)
  vi.mocked(listReviews).mockImplementation(() => settle(reviews))
  vi.mocked(listConfirmations).mockImplementation(() => settle(confirmations))
  vi.mocked(listSamples).mockImplementation(() => settle(samples))
}

afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

describe('Space workbench', () => {
  it('keeps the work entries in a 工作台 apart from the knowledge, with their open counts', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    counts([pointItem('cand-1', { pending_points: 4 }), pointItem('cand-2', { pending_points: 3 })],
      [confirmationItem('c1'), confirmationItem('c2')], [])
    const view = home()
    await flushPromises()
    expect(vi.mocked(listReviews).mock.calls).toEqual([['demo', 'pending']])
    expect(vi.mocked(listConfirmations).mock.calls).toEqual([['demo', 'open']])
    expect(vi.mocked(listSamples).mock.calls).toEqual([['demo', 'pending']])

    const workbench = view.get('[data-space-workbench]')
    expect(workbench.element.tagName).toBe('ASIDE')
    expect(workbench.text()).toContain('工作台')
    expect(count(view, 'reviews').text()).toContain('7')
    expect(count(view, 'confirmations').text()).toContain('2')
    expect(count(view, 'spotchecks').text()).toContain('无待办')
    expect(workbench.find('[data-space-search]').exists()).toBe(false)
    expect(workbench.find('[data-overview-row]').exists()).toBe(false)
    expect(view.find('[data-space-search]').exists()).toBe(true)

    // The three work pages are linked only from the workbench, each as its named route.
    const links = view.findAllComponents(RouterLinkStub)
    for (const [key, name] of Object.entries(ROUTES)) {
      const targets = links.filter(link => (link.props('to') as { name?: string }).name === name)
      expect(targets.length, name).toBeGreaterThan(0)
      for (const link of targets) {
        expect(link.props('to')).toEqual({ name, params: { spaceId: 'demo' } })
        expect(link.element.closest(`[data-workbench-entry="${key}"]`), name).not.toBeNull()
      }
    }
  })

  it('shows the home first and each count when it arrives', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const reviews = deferred<ReviewItem[]>(), confirmations = deferred<ConfirmationItem[]>(), samples = deferred<SpotSample[]>()
    vi.mocked(listReviews).mockReturnValue(reviews.promise)
    vi.mocked(listConfirmations).mockReturnValue(confirmations.promise)
    vi.mocked(listSamples).mockReturnValue(samples.promise)
    const view = home()
    await flushPromises()
    expect(view.find('[data-space-title]').exists()).toBe(true)
    for (const key of Object.keys(ROUTES)) expect(count(view, key).text()).toContain('…')
    samples.resolve([spotSample('s1'), spotSample('s2'), spotSample('s3')])
    await flushPromises()
    expect(count(view, 'spotchecks').text()).toContain('3')
    expect(count(view, 'reviews').text()).toContain('…')
    reviews.resolve([pointItem('cand-1', { pending_points: 2 })])
    confirmations.resolve([])
    await flushPromises()
    expect(count(view, 'reviews').text()).toContain('2')
    expect(count(view, 'confirmations').text()).toContain('无待办')
  })

  it.each([
    ['403 status', new EnterpriseError('FORBIDDEN', 403)],
    ['access denied code', new EnterpriseError('RELEASE_ACCESS_DENIED', 401)],
  ])('hides an entry the user may not open (%s) and keeps one whose count failed', async (_name, denial) => {
    vi.mocked(readRelease).mockResolvedValue(release())
    counts(denial, new EnterpriseError('SERVICE_UNAVAILABLE', 503), [spotSample('s1')])
    const view = home()
    await flushPromises()
    expect(entry(view, 'reviews').exists()).toBe(false)
    expect(entry(view, 'confirmations').exists()).toBe(true)
    expect(count(view, 'confirmations').exists()).toBe(false)
    expect(count(view, 'spotchecks').text()).toContain('1')
    const names = view.findAllComponents(RouterLinkStub).map(link => (link.props('to') as { name?: string }).name)
    expect(names).not.toContain('enterpriseReviews')
    expect(names).toContain('enterpriseConfirmations')
  })

  it('treats a malformed count as a failed one', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    counts([pointItem('cand-1', { pending_points: 1 })], [], [])
    vi.mocked(listConfirmations).mockResolvedValue(undefined as unknown as ConfirmationItem[])
    const view = home()
    await flushPromises()
    expect(entry(view, 'confirmations').exists()).toBe(true)
    expect(count(view, 'confirmations').exists()).toBe(false)
  })

  it('shows no workbench when every entry is hidden', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const denied = new EnterpriseError('RELEASE_ACCESS_DENIED', 403)
    counts(denied, denied, denied)
    const view = home()
    await flushPromises()
    expect(view.find('[data-space-workbench]').exists()).toBe(false)
    expect(view.find('[data-space-title]').exists()).toBe(true)
  })

  it('shows the workbench on a Space that has never published, beside its empty state', async () => {
    vi.mocked(readRelease).mockRejectedValue(new EnterpriseError('RELEASE_NOT_FOUND', 404))
    counts([pointItem('cand-1', { pending_points: 5 })], [confirmationItem('c1')], [])
    const view = home()
    await flushPromises()
    expect(view.text()).toContain('该空间还没有发布版本')
    expect(view.find('[data-space-search]').exists()).toBe(false)
    expect(vi.mocked(listReviews).mock.calls).toEqual([['demo', 'pending']])
    expect(view.get('[data-space-workbench]').text()).toContain('工作台')
    expect(count(view, 'reviews').text()).toContain('5')
    expect(count(view, 'confirmations').text()).toContain('1')
    expect(count(view, 'spotchecks').text()).toContain('无待办')
  })

  it('reads no counts when the release cannot be read, and reads them again on every visit', async () => {
    vi.mocked(readRelease).mockRejectedValueOnce(new EnterpriseError('SERVICE_UNAVAILABLE', 503))
    counts([], [], [])
    home()
    await flushPromises()
    expect(vi.mocked(listReviews)).not.toHaveBeenCalled()
    vi.mocked(readRelease).mockResolvedValue(release())
    home()
    await flushPromises()
    home()
    await flushPromises()
    expect(vi.mocked(listReviews)).toHaveBeenCalledTimes(2)
    expect(vi.mocked(listConfirmations)).toHaveBeenCalledTimes(2)
    expect(vi.mocked(listSamples)).toHaveBeenCalledTimes(2)
  })
})
