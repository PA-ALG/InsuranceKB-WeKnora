// @vitest-environment happy-dom
// S6d acceptance (protected, written by Claude): an expanded product in the knowledge navigation
// lists its native Wiki pages under "自由知识wiki" (S6d-3 rename), pinned to the release
// (Spec docs/design/slices/S6d-延伸阅读页面.md §1).
import { flushPromises, mount, RouterLinkStub, type VueWrapper } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import EnterpriseNavigation from './EnterpriseNavigation.vue'
import { wikiRelease } from './__tests__/wikiFixtures'

async function nav(entityId: string) {
  const view = mount(EnterpriseNavigation, {
    props: { release: wikiRelease(), spaceId: 'demo', entityId },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })], stubs: { RouterLink: RouterLinkStub } },
  })
  await flushPromises()
  return view
}

describe('further reading in the product navigation', () => {
  it('lists the expanded product\'s pages with their count, linked on the same release', async () => {
    const view = await nav('M1')
    const group = view.get('[data-nav-wiki]')
    expect([group.element.tagName, group.attributes('open')]).toEqual(['DETAILS', undefined]) // collapsed by default
    expect(group.text()).toContain('自由知识wiki')
    expect(group.text()).toContain('3')
    const links = group.findAllComponents(RouterLinkStub).map((link: VueWrapper<InstanceType<typeof RouterLinkStub>>) => link.props('to'))
    expect(links).toEqual([
      { name: 'enterpriseWikiPage', params: { spaceId: 'demo', entityId: 'M1', pageType: 'concept', pageSlug: 'deng-dai-qi' }, query: { release: 'rel-9' } },
      { name: 'enterpriseWikiPage', params: { spaceId: 'demo', entityId: 'M1', pageType: 'concept', pageSlug: 'kuan-xian-qi' }, query: { release: 'rel-9' } },
      { name: 'enterpriseWikiPage', params: { spaceId: 'demo', entityId: 'M1', pageType: 'entity', pageSlug: 'jia-yi-liao' }, query: { release: 'rel-9' } },
    ])
  })

  it('shows no group for a product without pages', async () => {
    const view = await nav('C1')
    expect(view.find('[data-nav-wiki]').exists()).toBe(false)
  })
})
