// @vitest-environment happy-dom
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import type { Component } from 'vue'
import { Drawer } from 'tdesign-vue-next'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import EnterpriseSpace from './EnterpriseSpace.vue'
import EnterpriseEntity from './EnterpriseEntity.vue'
import EnterpriseChanges from './EnterpriseChanges.vue'
import CitationPanel from './CitationPanel.vue'
import { readRelease, type Release } from './enterpriseApi'
import { baseRelease, currentRelease } from './__tests__/changesFixtures'
vi.mock('./enterpriseApi', async original => ({ ...await original<typeof import('./enterpriseApi')>(), readRelease: vi.fn() }))
const pages = { space: EnterpriseSpace, entity: EnterpriseEntity, changes: EnterpriseChanges }
type Page = keyof typeof pages
const views: ReturnType<typeof mount>[] = []
const deferred = <T>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
async function page(name: Page, props: Record<string, string> = {}) {
  const component: Component = pages[name]
  const view = mount(component, { attachTo: document.body, props: {
    spaceId: 'demo', releaseId: 'rel-9', ...(name === 'entity' ? { entityId: 'M1' } : {}), ...props,
  }, global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })], stubs: {
    RouterLink: RouterLinkStub, CitationPanel: true,
    't-drawer': { props: ['visible'], template: '<aside v-if="visible"><slot /></aside>' },
  } } })
  views.push(view); await flushPromises(); return view
}
afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

it.each<Page>(['space', 'entity', 'changes'])('ignores an old base response after changing Space on the %s page', async name => {
  const old = deferred<Release>()
  const latest = { ...currentRelease(), id: 'new-current', base_release_id: 'new-base' }
  vi.mocked(readRelease).mockImplementation(async (space, id) => space === 'demo'
    ? id === 'rel-8' ? old.promise : currentRelease()
    : id === 'new-base' ? { ...baseRelease(), id: 'new-base' } : latest)
  const view = await page(name)
  await view.setProps({ spaceId: 'next', releaseId: 'new-current' }); await flushPromises()
  const fresh = view.text()
  old.resolve({ ...baseRelease(), members: [] }); await flushPromises()
  expect(view.text()).toBe(fresh)
  expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-9'], ['demo', 'rel-8'], ['next', 'new-current'], ['next', 'new-base']])
})

it.each<Page>(['space', 'entity', 'changes'])('rejects an Active base without requesting it on the %s page', async name => {
  vi.mocked(readRelease).mockResolvedValue({ ...currentRelease(), base_release_id: 'active' })
  const view = await page(name)
  expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-9']])
  expect(view.find('[data-space-changes], [data-field-updated], [data-change]').exists()).toBe(false)
  expect(view.find('[role="alert"]').exists()).toBe(name === 'changes')
})

it.each<Page>(['space', 'entity', 'changes'])('rejects a response with the wrong base ID on the %s page', async name => {
  vi.mocked(readRelease).mockImplementation(async (_space, id) => id === 'rel-8' ? { ...baseRelease(), id: 'wrong' } : currentRelease())
  const view = await page(name)
  expect(view.find('[data-space-changes], [data-field-updated], [data-change]').exists()).toBe(false)
  expect(view.find('[role="alert"]').exists()).toBe(name === 'changes')
})

it('retries only the pinned base after a base failure', async () => {
  vi.mocked(readRelease).mockResolvedValueOnce(currentRelease()).mockRejectedValueOnce(new Error('unavailable')).mockResolvedValueOnce(baseRelease())
  const view = await page('changes')
  await view.get('[role="alert"] button').trigger('click'); await flushPromises()
  expect(view.find('[data-change="M1/waiting_period"]').exists()).toBe(true)
  expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-9'], ['demo', 'rel-8'], ['demo', 'rel-8']])
})

it('pins citations to their displayed side, restores focus and avoids duplicate anchors', async () => {
  vi.mocked(readRelease).mockImplementation(async (_space, id) => id === 'rel-8' ? baseRelease() : currentRelease())
  const view = await page('changes'), row = view.get('[data-change="M1/waiting_period"]')
  const ids = view.findAll('[id]').map(item => item.attributes('id'))
  expect(new Set(ids).size).toBe(ids.length)
  const before = row.get('[data-change-before] .ek-source')
  ;(before.element as HTMLButtonElement).focus(); await before.trigger('click'); await flushPromises()
  expect(view.getComponent(CitationPanel).props()).toMatchObject({ releaseId: 'rel-8', member: 'M1/waiting_period' })
  view.getComponent(Drawer).vm.$emit('close'); await flushPromises()
  expect(document.activeElement).toBe(before.element)
  await row.get('[data-change-after] .ek-source').trigger('click'); await flushPromises()
  expect(view.getComponent(CitationPanel).props()).toMatchObject({ releaseId: 'rel-9' })
})

it('expands an old field accessibly and keeps its citation on the base while current citations remain current', async () => {
  vi.mocked(readRelease).mockImplementation(async (_space, id) => id === 'rel-8' ? baseRelease() : currentRelease())
  const view = await page('entity'), row = view.get('[data-field="M1/waiting_period"]')
  const button = row.get('[data-field-updated]')
  expect(button.attributes('aria-expanded')).toBe('false')
  await button.trigger('click')
  expect(button.attributes('aria-expanded')).toBe('true')
  expect(row.get('[data-field-previous]').attributes('id')).toBe(button.attributes('aria-controls'))
  await row.get('[data-field-previous] .ek-source').trigger('click'); await flushPromises()
  expect(view.getComponent(CitationPanel).props()).toMatchObject({ releaseId: 'rel-8' })
  await button.trigger('click')
  expect(row.find('[data-field-previous]').exists()).toBe(false)
  await row.get('.ek-source').trigger('click'); await flushPromises()
  expect(view.getComponent(CitationPanel).props()).toMatchObject({ releaseId: 'rel-9' })
  await view.setProps({ entityId: 'C1' }); await flushPromises()
  expect(view.findComponent(CitationPanel).exists()).toBe(false)
  expect(view.find('[data-field-previous]').exists()).toBe(false)
})

it('discards a late current-release response before issuing any base read', async () => {
  const old = deferred<Release>()
  vi.mocked(readRelease).mockReturnValueOnce(old.promise).mockResolvedValueOnce({ ...baseRelease(), id: 'first' })
  const view = await page('changes')
  await view.setProps({ releaseId: 'first' }); await flushPromises()
  old.resolve(currentRelease()); await flushPromises()
  expect(view.text()).toContain('这是第一个发布版本')
  expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-9'], ['demo', 'first']])
})
