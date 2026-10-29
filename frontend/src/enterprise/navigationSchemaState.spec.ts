// @vitest-environment happy-dom
import { mount, RouterLinkStub, type VueWrapper } from '@vue/test-utils'
import { afterEach, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import enUS from '@/enterprise/i18n/locales/en-US'
import jaJP from '@/enterprise/i18n/locales/ja-JP'
import koKR from '@/enterprise/i18n/locales/ko-KR'
import ruRU from '@/enterprise/i18n/locales/ru-RU'
import EnterpriseNavigation from './EnterpriseNavigation.vue'
import { wikiRelease } from './__tests__/wikiFixtures'
import { claim } from './__tests__/s3eFixtures'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))
function nav(release = wikiRelease(), locale = 'zh-CN') {
  const wrapper = mount(EnterpriseNavigation, {
    props: { release, spaceId: 'demo', entityId: 'M1' },
    global: { plugins: [createI18n({ legacy: false, locale, messages: {
      'zh-CN': zhCN, 'en-US': enUS, 'ja-JP': jaJP, 'ko-KR': koKR, 'ru-RU': ruRU,
    } })], stubs: { RouterLink: RouterLinkStub } },
  })
  wrappers.push(wrapper)
  return wrapper
}
const schema = (wrapper: ReturnType<typeof nav>) => wrapper.get<HTMLDetailsElement>('[data-nav-schema]')
async function collapse(wrapper: ReturnType<typeof nav>) {
  const details = schema(wrapper)
  details.element.open = false
  await details.trigger('toggle')
  return details
}

it('preserves manual state on the same page and across closing and reopening the product', async () => {
  const wrapper = nav()
  await collapse(wrapper)
  await wrapper.setProps({ release: { ...wrapper.props('release') } })
  expect(schema(wrapper).element.open).toBe(false)
  const toggle = wrapper.get('.ek-nav-entry__toggle')
  await toggle.trigger('click')
  await toggle.trigger('click')
  expect(schema(wrapper).element.open).toBe(false)
  schema(wrapper).element.open = true
  await schema(wrapper).trigger('toggle')
  await wrapper.setProps({ release: { ...wrapper.props('release') } })
  expect(schema(wrapper).element.open).toBe(true)
})

// S3j (user 2026-10-21): each product keeps the reader's choice; another product starts open.
it('opens the schema of a different product and keeps the first product closed on return', async () => {
  const wrapper = nav()
  await collapse(wrapper)
  await wrapper.setProps({ entityId: 'C1' })
  expect(schema(wrapper).element.open).toBe(true)
  await collapse(wrapper)
  await wrapper.setProps({ entityId: 'M1' })
  expect(schema(wrapper).element.open).toBe(false)
})

it('restores on a new release and ignores a queued event from the old schema node', async () => {
  const wrapper = nav()
  const old = await collapse(wrapper)
  await wrapper.setProps({ release: { ...wrapper.props('release'), id: 'another-release' } })
  await old.trigger('toggle')
  expect(schema(wrapper).element.open).toBe(true)
  expect(schema(wrapper).findAllComponents(RouterLinkStub).every((link: VueWrapper<InstanceType<typeof RouterLinkStub>>) =>
    (link.props('to') as { query: { release: string } }).query.release === 'another-release')).toBe(true)
})

it('saves native schema state before its deferred toggle when the product is closed', async () => {
  const wrapper = nav()
  const details = schema(wrapper).element
  // Match the browser's queued toggle; happy-dom normally delivers it synchronously.
  details.addEventListener('toggle', event => event.stopImmediatePropagation(), { capture: true })
  details.open = false
  const toggle = wrapper.get('.ek-nav-entry__toggle')
  await toggle.trigger('click')
  await toggle.trigger('click')
  expect(schema(wrapper).element.open).toBe(false)
})

it('keeps schema and free-page states independent on the same product', async () => {
  const wrapper = nav()
  await collapse(wrapper)
  await wrapper.setProps({ wikiPageKey: 'concept/kuan-xian-qi' })
  expect(schema(wrapper).element.open).toBe(false)
  expect(wrapper.get<HTMLDetailsElement>('[data-nav-wiki]').element.open).toBe(true)
  expect(wrapper.get('[data-nav-wiki] [aria-current="page"]').text()).toBe('宽限期')
})

it('keeps all original field groups, their ordering and their pinned link targets', () => {
  const release = wikiRelease()
  const generated = claim('M1', 'model_note', 'present', 'Synthetic explanation')
  generated.payload.origin = 'MODEL_GENERATED'
  release.members.push(claim('M1', 'extra_note', 'present', 'Synthetic fact'), generated)
  const wrapper = nav(release)
  expect(schema(wrapper).findAll(':scope > details > summary').map(item => item.text()))
    .toEqual(['合同与交费', zhCN.enterpriseKnowledge.entity.other, zhCN.enterpriseKnowledge.entity.generated])
  expect(schema(wrapper).findAllComponents(RouterLinkStub).map((link: VueWrapper<InstanceType<typeof RouterLinkStub>>) => link.props('to'))).toEqual(
    ['cooling_off_period', 'premium_grace_period', 'waiting_period', 'extra_note', 'model_note'].map(key => ({
      name: 'enterpriseEntity', params: { spaceId: 'demo', entityId: 'M1' }, query: { release: 'rel-9' }, hash: `#${key}`,
    })),
  )
})

it('puts the empty-field message inside the only top-level schema node', async () => {
  const release = wikiRelease()
  release.members = release.members.filter(member => !(member.kind === 'claim' && member.payload.subject_ref === 'C1'))
  const wrapper = nav(release)
  await wrapper.setProps({ entityId: 'C1' })
  expect(wrapper.get('.ek-nav-fields').element.children.length).toBe(1)
  expect(schema(wrapper).get('.ek-page__note').text()).toBe(zhCN.enterpriseKnowledge.nav.noFields)
  expect(schema(wrapper).find('details').exists()).toBe(false)
  expect(wrapper.find('[data-nav-wiki]').exists()).toBe(false)
})

it.each([
  ['zh-CN', '自由知识wiki'], ['en-US', 'Free knowledge wiki'], ['ja-JP', '自由知識wiki'],
  ['ko-KR', '자유 지식 wiki'], ['ru-RU', 'Свободная вики знаний'],
])('uses the frozen navigation labels in %s', (locale, label) => {
  const wrapper = nav(wikiRelease(), locale)
  expect(schema(wrapper).get('summary').text()).toBe('schema_wiki')
  expect(wrapper.get('[data-nav-wiki] > summary').text()).toBe(`${label} 3`)
})
