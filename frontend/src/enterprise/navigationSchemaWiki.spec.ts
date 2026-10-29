// @vitest-environment happy-dom
// S6d-3 acceptance (protected, written by Claude): an expanded product shows two top nodes, schema_wiki
// (open, holding every field group) then 自由知识wiki (collapsed, with its page count)
// (Spec docs/design/slices/S6d-3-schema_wiki与自由知识wiki.md §1).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
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

const summary = (node: Element) => node.querySelector(':scope > summary')?.textContent?.replace(/\s+/g, ' ').trim()

describe('product navigation nodes', () => {
  it('puts every field group under schema_wiki, then the free pages under 自由知识wiki', async () => {
    const view = await nav('M1')
    const fields = view.get('.ek-nav-fields').element
    const top = [...fields.children].filter(node => node.tagName === 'DETAILS')
    expect(top.map(node => [node.hasAttribute('data-nav-schema'), node.hasAttribute('data-nav-wiki')]))
      .toEqual([[true, false], [false, true]])
    const [schema, wiki] = top as HTMLDetailsElement[]
    expect(summary(schema!)).toBe('schema_wiki')
    expect(schema!.open).toBe(true)
    expect(summary(wiki!)).toBe('自由知识wiki 3')
    expect(wiki!.open).toBe(false)

    const groups = [...schema!.querySelectorAll(':scope details')]
    expect(groups.length).toBeGreaterThan(0)
    const fieldLinks = view.findAll('.ek-nav-fields a').filter(link => !link.element.closest('[data-nav-wiki]'))
    expect(fieldLinks.length).toBeGreaterThan(0)
    expect(fieldLinks.every(link => schema!.contains(link.element))).toBe(true)
  })

  it('shows only schema_wiki for a product without free pages', async () => {
    const view = await nav('C1')
    expect(view.find('[data-nav-schema]').exists()).toBe(true)
    expect(view.find('[data-nav-wiki]').exists()).toBe(false)
  })
})
