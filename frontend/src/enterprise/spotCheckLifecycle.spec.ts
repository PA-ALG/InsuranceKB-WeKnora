// @vitest-environment happy-dom
import { readFileSync } from 'node:fs'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, expect, it, vi } from 'vitest'
import { Drawer } from 'tdesign-vue-next'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
vi.mock('./enterpriseApi', async original => ({ ...await original<typeof import('./enterpriseApi')>(),
  listSamples: vi.fn(), readRelease: vi.fn(), submitVerdict: vi.fn() }))
import { EnterpriseError, listSamples, readRelease, submitVerdict } from './enterpriseApi'
import EnterpriseSpotChecks from './EnterpriseSpotChecks.vue'
import CitationPanel from './CitationPanel.vue'
import { spotRelease, spotSample, spotVerdict } from './__tests__/spotCheckFixtures'
const styles = ['enterprisePage.css', 'spotChecks.css']
  .map(name => readFileSync(new URL(name, import.meta.url), 'utf8')).join('\n')
const views: ReturnType<typeof mount>[] = []
const deferred = <T>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
async function page() {
  const view = mount(EnterpriseSpotChecks, { attachTo: document.body, props: { spaceId: 'demo' }, global: {
    plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
    stubs: { RouterLink: RouterLinkStub, CitationPanel: true },
  } })
  views.push(view); await flushPromises(); return view
}
afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

it('gives all three verdict choices the same visual weight', async () => {
  vi.mocked(listSamples).mockResolvedValue([spotSample()])
  vi.mocked(readRelease).mockResolvedValue(spotRelease())
  const style = document.createElement('style')
  style.textContent = `:root { --td-brand-color: #0052d9; --td-text-color-primary: #222222; --td-border-level-2-color: #dddddd; --td-bg-color-container: #ffffff; }\n${styles}`
  document.head.append(style)
  try {
    const view = await page()
    const buttons = view.findAll('[data-verdict]')
    expect(buttons).toHaveLength(3)
    const appearances = buttons.map(button => {
      const css = getComputedStyle(button.element)
      return [css.color, css.borderTopColor, css.backgroundColor, css.fontWeight, css.opacity]
    })
    expect(appearances[0]![0]).toBeTruthy()
    expect(appearances[0]).toEqual(appearances[1])
    expect(appearances[1]).toEqual(appearances[2])
  } finally { style.remove() }
})

it('deduplicates sample IDs, shares a pinned release across tabs, and returns source focus on close', async () => {
  vi.mocked(listSamples).mockImplementation((_space, status) => Promise.resolve(status === 'pending'
    ? [spotSample(), spotSample()] : [spotSample('sample-2', 'rel-old', { verdict: spotVerdict('sample-2') })]))
  vi.mocked(readRelease).mockResolvedValue(spotRelease())
  const view = await page()
  expect(view.findAll('[data-spot-sample]')).toHaveLength(1)
  const source = view.get('.ek-source'); (source.element as HTMLElement).focus(); await source.trigger('click')
  expect(view.getComponent(CitationPanel).props()).toMatchObject({ releaseId: 'rel-old', member: 'item/term', evidence: 0 })
  view.getComponent(Drawer).vm.$emit('close'); await flushPromises()
  expect(document.activeElement).toBe(source.element)
  await view.get('[data-spot-tab="decided"]').trigger('click'); await flushPromises()
  expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-old']])
})

it('blocks mismatched, inaccessible and ambiguous members and never reads Active for an invalid pin', async () => {
  const data = spotRelease()
  data.members.push({ ...data.members[2]!, logical_slug: 'private/term', access_scope: 'restricted' })
  data.members.push(...Array.from({ length: 2 }, () => ({ ...data.members[2]!, logical_slug: 'ambiguous/term' })))
  vi.mocked(listSamples).mockResolvedValue([
    spotSample('changed', 'rel-old', { member_digest: 'other' }),
    spotSample('private', 'rel-old', { logical_slug: 'private/term' }),
    spotSample('ambiguous', 'rel-old', { logical_slug: 'ambiguous/term' }),
    spotSample('invalid', 'active'),
  ])
  vi.mocked(readRelease).mockResolvedValue(data)
  const view = await page()
  expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-old']])
  for (const id of ['changed', 'private', 'ambiguous']) {
    const card = view.get(`[data-spot-sample="${id}"]`)
    expect(card.text()).toContain('该条目已变化')
    expect(card.get('textarea').attributes('disabled')).toBeDefined()
    expect(card.findAll('[data-verdict]').every(button => button.attributes('disabled') !== undefined)).toBe(true)
  }
  expect(view.get('[data-spot-sample="invalid"]').findAll('[data-verdict]').every(button => button.attributes('disabled') !== undefined)).toBe(true)
  expect(submitVerdict).not.toHaveBeenCalled()
})

it('retries only a failed pinned Release and rejects a response for a different Release', async () => {
  vi.mocked(listSamples).mockResolvedValue([spotSample()])
  vi.mocked(readRelease).mockRejectedValueOnce(new EnterpriseError('RELEASE_NOT_FOUND', 404))
    .mockResolvedValueOnce(spotRelease('other')).mockResolvedValueOnce(spotRelease())
  const view = await page()
  const group = () => view.get('[data-spot-release="rel-old"]')
  await group().get('[role="alert"] button').trigger('click'); await flushPromises()
  expect(group().findAll('[data-verdict]').every(button => button.attributes('disabled') !== undefined)).toBe(true)
  await group().get('[role="alert"] button').trigger('click'); await flushPromises()
  expect(group().text()).toContain('已发布的字段内容')
  expect(vi.mocked(readRelease).mock.calls).toEqual(Array(3).fill(['demo', 'rel-old']))
  expect(listSamples).toHaveBeenCalledTimes(1)
})

it('ignores old Space list responses after navigation', async () => {
  const old = deferred<ReturnType<typeof spotSample>[]>()
  vi.mocked(listSamples).mockReturnValueOnce(old.promise).mockResolvedValueOnce([spotSample('new', 'rel-new', { space_id: 'next' })])
  vi.mocked(readRelease).mockResolvedValue(spotRelease('rel-new', 2, '新空间内容'))
  const view = await page(); await view.setProps({ spaceId: 'next' }); await flushPromises()
  old.resolve([spotSample()]); await flushPromises()
  expect(view.find('[data-spot-sample="sample-1"]').exists()).toBe(false)
  expect(view.text()).toContain('新空间内容')
  expect(vi.mocked(readRelease).mock.calls).toEqual([['next', 'rel-new']])
})

it('ignores an old tab response while keeping the selected tab keyboard reachable', async () => {
  const old = deferred<ReturnType<typeof spotSample>[]>()
  vi.mocked(listSamples).mockReturnValueOnce(old.promise).mockResolvedValueOnce([spotSample('done', 'rel-old', { verdict: spotVerdict('done') })])
  vi.mocked(readRelease).mockResolvedValue(spotRelease())
  const view = await page()
  await view.get('[data-spot-tab="pending"]').trigger('keydown', { key: 'ArrowRight' }); await flushPromises()
  old.resolve([spotSample()]); await flushPromises()
  expect(view.get('[data-spot-tab="decided"]').attributes('aria-selected')).toBe('true')
  expect(view.find('[data-spot-sample="sample-1"]').exists()).toBe(false)
  expect(view.get('[data-spot-sample="done"]').text()).toContain('reviewer:demo')
})

it('keeps a failed draft, validates Unicode length, prevents duplicate sends, and shows success in decided', async () => {
  vi.mocked(listSamples).mockResolvedValue([spotSample()])
  vi.mocked(readRelease).mockResolvedValue(spotRelease())
  const pending = deferred<ReturnType<typeof spotVerdict>>()
  vi.mocked(submitVerdict).mockRejectedValueOnce(new EnterpriseError('REQUEST_FAILED')).mockReturnValueOnce(pending.promise)
  const view = await page(), note = () => view.get('textarea'), button = () => view.get('[data-verdict="incomplete"]')
  expect(note().attributes('disabled')).toBeUndefined()
  await note().setValue('字'.repeat(1001)); expect(button().attributes('disabled')).toBeDefined()
  await note().setValue('😀'.repeat(1000)); expect(button().attributes('disabled')).toBeUndefined()
  await note().setValue('请补充适用条件'); await button().trigger('click'); await flushPromises()
  expect(note().attributes('disabled')).toBeUndefined()
  expect((note().element as HTMLTextAreaElement).value).toBe('请补充适用条件')
  await button().trigger('click'); await button().trigger('click')
  expect(note().attributes('disabled')).toBeDefined()
  expect(view.findAll('[data-verdict]').every(choice => choice.attributes('disabled') !== undefined)).toBe(true)
  expect(submitVerdict).toHaveBeenCalledTimes(2)
  pending.resolve(spotVerdict()); await flushPromises()
  expect(view.find('[data-spot-sample="sample-1"]').exists()).toBe(false)
  vi.mocked(listSamples).mockResolvedValueOnce([])
  await view.get('[data-spot-tab="decided"]').trigger('click'); await flushPromises()
  expect(view.get('[data-spot-sample="sample-1"]').text()).toContain('请补充适用条件')
})

it('does not reuse or apply an old Release read after switching Spaces, even if release IDs coincide', async () => {
  const old = deferred<ReturnType<typeof spotRelease>>()
  vi.mocked(listSamples).mockImplementation(space => Promise.resolve([spotSample('sample-1', 'rel-old', { space_id: space })]))
  vi.mocked(readRelease).mockReturnValueOnce(old.promise).mockResolvedValueOnce(spotRelease('rel-old', 2, '新空间内容'))
  const view = await page()
  await view.setProps({ spaceId: 'next' }); await flushPromises()
  old.resolve(spotRelease('rel-old', 1, '旧空间内容')); await flushPromises()
  expect(view.text()).toContain('新空间内容')
  expect(view.text()).not.toContain('旧空间内容')
  expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-old'], ['next', 'rel-old']])
})

it('clears a previous Space drawer and draft, and ignores a verdict completed after navigation', async () => {
  vi.mocked(listSamples).mockImplementation(space => Promise.resolve([spotSample('sample-1', 'rel-old', { space_id: space })]))
  vi.mocked(readRelease).mockResolvedValue(spotRelease())
  const pending = deferred<ReturnType<typeof spotVerdict>>()
  vi.mocked(submitVerdict).mockReturnValueOnce(pending.promise)
  const view = await page()
  await view.get('textarea').setValue('旧空间说明')
  await view.get('[data-verdict="correct"]').trigger('click')
  await view.get('.ek-source').trigger('click')
  expect(view.findComponent(CitationPanel).exists()).toBe(true)
  await view.setProps({ spaceId: 'next' }); await flushPromises()
  expect(view.findComponent(CitationPanel).exists()).toBe(false)
  expect((view.get('textarea').element as HTMLTextAreaElement).value).toBe('')
  pending.resolve(spotVerdict()); await flushPromises()
  expect(view.find('[data-spot-sample="sample-1"]').exists()).toBe(true)
  expect(view.get('[data-verdict="correct"]').attributes('disabled')).toBeUndefined()
})

it('preserves an unfinished note while changing tabs', async () => {
  vi.mocked(listSamples).mockImplementation((_space, status) => Promise.resolve(status === 'pending' ? [spotSample()] : []))
  vi.mocked(readRelease).mockResolvedValue(spotRelease())
  const view = await page()
  await view.get('textarea').setValue('稍后继续核对')
  await view.get('[data-spot-tab="decided"]').trigger('click'); await flushPromises()
  await view.get('[data-spot-tab="pending"]').trigger('click'); await flushPromises()
  expect((view.get('textarea').element as HTMLTextAreaElement).value).toBe('稍后继续核对')
  expect(readRelease).toHaveBeenCalledTimes(1)
})
