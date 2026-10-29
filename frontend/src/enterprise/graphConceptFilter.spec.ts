// @vitest-environment happy-dom
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
vi.mock('./enterpriseApi', async original => ({ ...await original<typeof import('./enterpriseApi')>(), readRelease: vi.fn() }))
import { readRelease } from './enterpriseApi'
import EnterpriseGraph from './EnterpriseGraph.vue'
import { release } from './__tests__/s3eFixtures'

function data() {
  const result = structuredClone(release())
  result.members = result.members.filter(member => member.payload.entity_id !== 'X1' && member.payload.subject_ref !== 'X1')
  return result
}
const views: ReturnType<typeof mount>[] = []
async function page() {
  vi.mocked(readRelease).mockResolvedValue(data())
  const view = mount(EnterpriseGraph, { props: { spaceId: 'demo', releaseId: 'rel-9' }, attachTo: document.body,
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })], stubs: { RouterLink: RouterLinkStub } } })
  views.push(view)
  await flushPromises()
  return view
}
const shared = '[data-graph-node="concept:cooling_off_period"]'
afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

describe('graph external location', () => {
  it('uses the same reveal path for external location and resets it on a new release', async () => {
    const view = await page()
    expect(await view.vm.locateNode('concept:cooling_off_period')).toBe(true)
    expect(view.find(shared).exists()).toBe(true)
    expect(view.get('[data-graph-detail]').text()).toContain('犹豫期')
    expect(await view.vm.locateNode('concept:missing')).toBe(false)
    vi.mocked(readRelease).mockResolvedValueOnce({ ...data(), id: 'next-release' })
    await view.setProps({ releaseId: 'next-release' })
    await flushPromises()
    expect(view.find(shared).exists()).toBe(false)
    expect(view.find('[data-graph-detail]').exists()).toBe(false)
    expect((view.get('[data-graph-all-concepts] input').element as HTMLInputElement).checked).toBe(false)
  })
})
