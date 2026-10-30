// @vitest-environment happy-dom
// S3h-2 acceptance (protected, written by Claude): the Space home, a changes page and the product
// page show what changed relative to the base release, every read pinned by release id
// (Spec docs/design/slices/S3h-全文搜索与本版变化.md §3.2).
import { flushPromises, mount, RouterLinkStub, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import EnterpriseChanges from './EnterpriseChanges.vue'
import EnterpriseEntity from './EnterpriseEntity.vue'
import EnterpriseSpace from './EnterpriseSpace.vue'
import { EnterpriseError, readRelease, type Release } from './enterpriseApi'
import { baseRelease, currentRelease, navigationOnlyRelease } from './__tests__/changesFixtures'
import { release } from './__tests__/s3eFixtures'

const global = {
  plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
  stubs: { RouterLink: RouterLinkStub, CitationPanel: true },
}

function serve(current: Release, base: Release | Error = baseRelease()) {
  vi.mocked(readRelease).mockImplementation(async (_space: string, id?: string) => {
    if (id === 'rel-8') {
      if (base instanceof Error) throw base
      return base
    }
    return current
  })
}

const links = (view: VueWrapper | ReturnType<VueWrapper['get']>) =>
  view.findAllComponents(RouterLinkStub).map((link: VueWrapper<InstanceType<typeof RouterLinkStub>>) => link.props('to'))

afterEach(() => { vi.resetAllMocks() })

describe('Space home: this release compared with its base', () => {
  it('counts the claim changes and links to the changes page on the same release', async () => {
    serve(currentRelease())
    const view = mount(EnterpriseSpace, { props: { spaceId: 'demo' }, global })
    await flushPromises()
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo'], ['demo', 'rel-8']])
    const line = view.get('[data-space-changes]')
    expect(line.text()).toContain('新增 1')
    expect(line.text()).toContain('修改 2')
    expect(line.text()).toContain('删除 1')
    expect(links(line)).toContainEqual({ name: 'enterpriseChanges', params: { spaceId: 'demo' }, query: { release: 'rel-9' } })
  })

  it('shows no line without claim changes, without a base, or when the base cannot be read', async () => {
    serve(navigationOnlyRelease())
    const quiet = mount(EnterpriseSpace, { props: { spaceId: 'demo' }, global })
    await flushPromises()
    expect(quiet.find('[data-space-changes]').exists()).toBe(false)

    serve(release())
    const first = mount(EnterpriseSpace, { props: { spaceId: 'demo' }, global })
    await flushPromises()
    expect(first.find('[data-space-changes]').exists()).toBe(false)
    expect(readRelease).toHaveBeenCalledTimes(3) // 2 above, 1 here: no base read without base_release_id

    serve(currentRelease(), new EnterpriseError('SERVICE_UNAVAILABLE', 503))
    const failed = mount(EnterpriseSpace, { props: { spaceId: 'demo' }, global })
    await flushPromises()
    expect(failed.find('[data-space-changes]').exists()).toBe(false)
    expect(failed.find('[data-space-title]').exists()).toBe(true)
  })
})

describe('changes page', () => {
  it('groups the changes by product, shows both sides of a change and links to the field', async () => {
    serve(currentRelease())
    const view = mount(EnterpriseChanges, { props: { spaceId: 'demo', releaseId: 'rel-9' }, global })
    await flushPromises()
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-9'], ['demo', 'rel-8']])
    expect(view.text()).toContain('版本 15 相对版本 14 的变化')
    expect(view.findAll('[data-change-entity]').map(group => group.attributes('data-change-entity'))).toEqual(['M1', 'C1'])
    const changed = view.get('[data-change="M1/waiting_period"]')
    expect(changed.text()).toContain('修改')
    expect(changed.get('[data-change-before]').text()).toContain('90日')
    expect(changed.get('[data-change-after]').text()).toContain('180日')
    expect(links(changed)).toContainEqual({
      name: 'enterpriseEntity', params: { spaceId: 'demo', entityId: 'M1' }, query: { release: 'rel-9' }, hash: '#waiting_period',
    })
    expect(view.get('[data-change="C1/waiting_period"]').text()).toContain('新增')
    const removed = view.get('[data-change="M1/premium_grace_period"]')
    expect(removed.text()).toContain('删除')
    expect(links(removed)).toEqual([])
  })

  it('explains when only non-field members changed, and when there is no earlier release', async () => {
    serve(navigationOnlyRelease())
    const quiet = mount(EnterpriseChanges, { props: { spaceId: 'demo', releaseId: 'rel-9' }, global })
    await flushPromises()
    expect(quiet.text()).toContain('本版没有字段内容变化')

    serve(release())
    const first = mount(EnterpriseChanges, { props: { spaceId: 'demo', releaseId: 'rel-9' }, global })
    await flushPromises()
    expect(first.text()).toContain('这是第一个发布版本')
  })

  it('shows a retryable failure', async () => {
    vi.mocked(readRelease).mockRejectedValueOnce(new EnterpriseError('SERVICE_UNAVAILABLE', 503))
      .mockImplementation(async (_space: string, id?: string) => id === 'rel-8' ? baseRelease() : currentRelease())
    const view = mount(EnterpriseChanges, { props: { spaceId: 'demo', releaseId: 'rel-9' }, global })
    await flushPromises()
    await view.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(view.find('[data-change="M1/waiting_period"]').exists()).toBe(true)
  })
})

describe('product page', () => {
  it('marks fields updated in this release and reveals the previous value', async () => {
    serve(currentRelease())
    const view = mount(EnterpriseEntity, { props: { spaceId: 'demo', entityId: 'M1', releaseId: 'rel-9' }, global })
    await flushPromises()
    expect(view.find('[data-field="M1/cooling_off_period"] [data-field-updated]').exists()).toBe(false)
    const updated = view.get('[data-field="M1/waiting_period"] [data-field-updated]')
    expect(updated.text()).toContain('本版更新')
    await updated.trigger('click')
    expect(view.get('[data-field="M1/waiting_period"] [data-field-previous]').text()).toContain('90日')

    serve(currentRelease())
    const added = mount(EnterpriseEntity, { props: { spaceId: 'demo', entityId: 'C1', releaseId: 'rel-9' }, global })
    await flushPromises()
    await added.get('[data-field="C1/waiting_period"] [data-field-updated]').trigger('click')
    expect(added.get('[data-field="C1/waiting_period"] [data-field-previous]').text()).toContain('上一版没有这一项')
  })

  it('shows no marks when the base release cannot be read', async () => {
    serve(currentRelease(), new EnterpriseError('SERVICE_UNAVAILABLE', 503))
    const view = mount(EnterpriseEntity, { props: { spaceId: 'demo', entityId: 'M1', releaseId: 'rel-9' }, global })
    await flushPromises()
    expect(view.find('[data-field="M1/waiting_period"]').exists()).toBe(true)
    expect(view.find('[data-field-updated]').exists()).toBe(false)
  })
})
