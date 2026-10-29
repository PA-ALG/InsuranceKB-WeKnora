// @vitest-environment happy-dom
// S3h-1 acceptance (protected, written by Claude): the Space home search also lists field-content
// hits, pinned to the release it read (Spec docs/design/slices/S3h-全文搜索与本版变化.md §2.2).
import { flushPromises, mount, RouterLinkStub, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import EnterpriseSpace from './EnterpriseSpace.vue'
import { readRelease, type Release } from './enterpriseApi'
import { claim, release } from './__tests__/s3eFixtures'

async function page(data: Release = release()) {
  vi.mocked(readRelease).mockResolvedValue(data)
  const view = mount(EnterpriseSpace, {
    props: { spaceId: 'demo' },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })], stubs: { RouterLink: RouterLinkStub } },
  })
  await flushPromises()
  return view
}

async function type(view: Awaited<ReturnType<typeof page>>, value: string) {
  await view.get('[data-space-search] input').setValue(value)
  await flushPromises()
}

afterEach(() => { vi.resetAllMocks() })

describe('Space home field search', () => {
  it('shows no field section until something is typed', async () => {
    const view = await page()
    expect(view.find('[data-search-fields]').exists()).toBe(false)
  })

  it('lists field hits with marked matches, linked to the field on the same release', async () => {
    const view = await page()
    await type(view, '20日')
    const hits = view.findAll('[data-search-hit]')
    expect(hits).toHaveLength(1)
    expect(hits[0]!.text()).toContain('丙重疾')
    expect(hits[0]!.text()).toContain('犹豫期')
    expect(hits[0]!.findAll('mark').map(mark => mark.text())).toEqual(['20日'])
    expect(hits[0]!.findAllComponents(RouterLinkStub).map((link: VueWrapper<InstanceType<typeof RouterLinkStub>>) => link.props('to')))
      .toContainEqual({
      name: 'enterpriseEntity', params: { spaceId: 'demo', entityId: 'C1' }, query: { release: 'rel-9' }, hash: '#cooling_off_period',
    })
  })

  it('says how many hits there are when more than fifty match', async () => {
    const data = structuredClone(release())
    data.members.push(...Array.from({ length: 60 }, (_, index) => claim('M1', `extra_${index}`, 'present', '命中词出现在这里。')))
    const view = await page(data)
    await type(view, '命中词')
    expect(view.findAll('[data-search-hit]')).toHaveLength(50)
    expect(view.get('[data-search-fields]').text()).toContain('共 60 条，显示前 50 条')
  })

  it('says so when nothing at all matches', async () => {
    const view = await page()
    await type(view, 'zzz')
    expect(view.text()).toContain('没有找到包含“zzz”的内容')
    expect(view.findAll('[data-search-hit]')).toHaveLength(0)
  })
})
