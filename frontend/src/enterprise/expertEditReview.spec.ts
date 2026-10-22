// @vitest-environment happy-dom
// S9b implementer regressions from review (#298 R1, R2): a stale edit on the Active route reads
// the Active release again; the form shows a present value of any type as the current value.
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { createI18n } from 'vue-i18n'
import { routeLocationKey, routerKey } from 'vue-router'
import zhCN from '@/i18n/locales/zh-CN'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasRole: () => true }) }))
vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import EnterpriseEntity from './EnterpriseEntity.vue'
import ExpertEditForm from './ExpertEditForm.vue'
import { readRelease, type Release } from './enterpriseApi'

const i18n = () => createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })

function release(id: string, epoch: number, value: unknown = '90日'): Release {
  return {
    id, epoch,
    members: [{
      kind: 'claim', logical_slug: 'P1/f_wait', member_digest: 'd'.repeat(64), access_scope: 'space',
      payload: { subject_ref: 'P1', predicate: 'f_wait', state: 'present', value, origin: 'SOURCE_SUPPORTED', evidence: [] },
    }],
  }
}

afterEach(() => { vi.resetAllMocks() })

describe('a stale edit on the Active route', () => {
  it('reads the Active release again instead of a duplicate navigation', async () => {
    vi.mocked(readRelease)
      .mockResolvedValueOnce(release('rel-1', 1))
      .mockResolvedValueOnce(release('rel-2', 2))
    const replace = vi.fn(() => Promise.resolve())
    const view = mount(EnterpriseEntity, {
      props: { spaceId: 'demo', entityId: 'P1' },
      global: {
        plugins: [createPinia(), i18n()],
        stubs: { RouterLink: RouterLinkStub, CitationPanel: true, ExpertEditForm: true, EnterpriseNavigation: true },
        provide: {
          [routerKey as symbol]: { replace, afterEach: () => () => undefined },
          [routeLocationKey as symbol]: reactive({ query: { tab: 'fields' }, hash: '#f_wait' }),
        },
      },
    })
    await flushPromises()
    expect(view.get('[data-entity-meta]').text()).toContain('发布版本 1')
    await view.get('[data-expert-edit]').trigger('click')
    view.getComponent(ExpertEditForm).vm.$emit('reload')
    await flushPromises()
    expect(replace).not.toHaveBeenCalled()
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo'], ['demo']])
    expect(view.findComponent(ExpertEditForm).exists()).toBe(false)
    expect(view.get('[data-entity-meta]').text()).toContain('发布版本 2')
  })
})

describe('the current value in the form', () => {
  it.each([
    [42, '42'],
    [false, 'false'],
    [{ min: 0, max: 60 }, '{"min":0,"max":60}'],
  ])('shows %j and leaves the new value empty', async (value, shown) => {
    const form = mount(ExpertEditForm, {
      props: { spaceId: 'demo', release: release('rel-1', 1, value), slug: 'P1/f_wait', title: '等待期' },
      global: { plugins: [i18n()] },
    })
    expect(form.get('[data-current]').text()).toBe(shown)
    expect((form.get('[data-value]').element as HTMLTextAreaElement).value).toBe('')
  })

  it('treats a number typed back unchanged as no change', async () => {
    const form = mount(ExpertEditForm, {
      props: { spaceId: 'demo', release: release('rel-1', 1, 42), slug: 'P1/f_wait', title: '等待期' },
      global: { plugins: [i18n()] },
    })
    await form.get('[data-reason]').setValue('核对')
    await form.get('[data-value]').setValue(' 42 ')
    expect(form.get('[data-submit]').attributes('disabled')).toBeDefined()
    await form.get('[data-value]').setValue('43')
    expect(form.get('[data-submit]').attributes('disabled')).toBeUndefined()
  })
})
