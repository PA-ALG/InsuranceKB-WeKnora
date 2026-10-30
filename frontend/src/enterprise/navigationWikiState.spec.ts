// @vitest-environment happy-dom
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import EnterpriseNavigation from './EnterpriseNavigation.vue'
import { wikiPage, wikiRelease } from './__tests__/wikiFixtures'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

function nav(wikiPageKey?: string) {
  const release = wikiRelease()
  release.members.push(wikiPage('M2', 'concept/kuan-xian-qi', '另一个产品的同名页'))
  const wrapper = mount(EnterpriseNavigation, {
    props: { release, spaceId: 'demo', entityId: 'M1', wikiPageKey },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub } },
  })
  wrappers.push(wrapper)
  return wrapper
}

it('preserves a manual collapse on the same page, including closing and reopening the product', async () => {
  const wrapper = nav('concept/kuan-xian-qi')
  const details = wrapper.get<HTMLDetailsElement>('[data-nav-wiki]')
  details.element.open = false
  await details.trigger('toggle')
  await wrapper.setProps({ release: { ...wrapper.props('release') } })
  expect(details.element.open).toBe(false)
  const toggle = wrapper.get('.ek-nav-entry__toggle')
  await toggle.trigger('click')
  await toggle.trigger('click')
  expect(wrapper.get<HTMLDetailsElement>('[data-nav-wiki]').element.open).toBe(false)
  await wrapper.setProps({ wikiPageKey: 'concept/deng-dai-qi' })
  expect(wrapper.get<HTMLDetailsElement>('[data-nav-wiki]').element.open).toBe(true)
  expect(wrapper.findAll('[aria-current="page"]').map(link => link.text())).toEqual(['等待期'])
})

// S3j (user 2026-10-21): the reader's choice survives page changes, including a missing page.
it('preserves a manual expansion across pages, then leaves a release without pages', async () => {
  const wrapper = nav()
  const details = wrapper.get<HTMLDetailsElement>('[data-nav-wiki]')
  details.element.open = true
  await details.trigger('toggle')
  await wrapper.setProps({ release: { ...wrapper.props('release') } })
  expect(details.element.open).toBe(true)
  await wrapper.setProps({ wikiPageKey: 'concept/missing' })
  expect(wrapper.get<HTMLDetailsElement>('[data-nav-wiki]').element.open).toBe(true)
  await wrapper.setProps({ wikiPageKey: 'concept/kuan-xian-qi' })
  expect(wrapper.get<HTMLDetailsElement>('[data-nav-wiki]').element.open).toBe(true)
  await wrapper.setProps({ release: { ...wrapper.props('release'), id: 'next', members: [] } })
  expect(wrapper.find('[data-nav-wiki]').exists()).toBe(false)
})

it('saves the native details state when closing the product before its deferred toggle event', async () => {
  const wrapper = nav('concept/kuan-xian-qi')
  const details = wrapper.get<HTMLDetailsElement>('[data-nav-wiki]').element
  // happy-dom dispatches synchronously; withhold it to reproduce the browser's queued event.
  details.addEventListener('toggle', event => event.stopImmediatePropagation(), { capture: true })
  details.open = false
  const toggle = wrapper.get('.ek-nav-entry__toggle')
  await toggle.trigger('click')
  await toggle.trigger('click')
  expect(wrapper.get<HTMLDetailsElement>('[data-nav-wiki]').element.open).toBe(false)
})

it('only marks the selected product even when another product has the same page key', async () => {
  const wrapper = nav('concept/kuan-xian-qi')
  await wrapper.findAll('.ek-nav-entry__toggle')[1]!.trigger('click')
  await flushPromises()
  const groups = wrapper.findAll<HTMLDetailsElement>('[data-nav-wiki]')
  expect(groups.map(group => group.element.open)).toEqual([true, false])
  expect(groups[1]!.find('[aria-current]').exists()).toBe(false)
  await wrapper.setProps({ entityId: 'M2' })
  expect(wrapper.findAll('[data-nav-wiki] [aria-current="page"]').map(link => link.text())).toEqual(['另一个产品的同名页'])
})

it('ignores an old group toggle delivered after switching to another page', async () => {
  const wrapper = nav('concept/kuan-xian-qi')
  const oldDetails = wrapper.get<HTMLDetailsElement>('[data-nav-wiki]')
  oldDetails.element.open = false
  await oldDetails.trigger('toggle')
  await wrapper.setProps({ wikiPageKey: 'concept/deng-dai-qi' })
  await oldDetails.trigger('toggle')
  expect(wrapper.get<HTMLDetailsElement>('[data-nav-wiki]').element.open).toBe(true)
})
