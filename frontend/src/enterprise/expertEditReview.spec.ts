// @vitest-environment happy-dom
// S9b implementer regressions from review (#298 R1–R4): a stale edit on the Active route reads the
// Active release again (only with a router); the form shows a present value of any type as the
// current value and leaves comparing typed text with a non-text value to the server.
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

describe('a stale edit without a router', () => {
  it('only closes the form and keeps the page (#298 R3)', async () => {
    vi.mocked(readRelease).mockResolvedValueOnce(release('rel-1', 1)).mockRejectedValue(new Error('offline'))
    const view = mount(EnterpriseEntity, {
      props: { spaceId: 'demo', entityId: 'P1' },
      global: {
        plugins: [createPinia(), i18n()],
        stubs: { RouterLink: RouterLinkStub, CitationPanel: true, ExpertEditForm: true, EnterpriseNavigation: true },
      },
    })
    await flushPromises()
    await view.get('[data-expert-edit]').trigger('click')
    view.getComponent(ExpertEditForm).vm.$emit('reload')
    await flushPromises()
    expect(vi.mocked(readRelease)).toHaveBeenCalledTimes(1)
    expect(view.findComponent(ExpertEditForm).exists()).toBe(false)
    expect(view.get('[data-entity-meta]').text()).toContain('发布版本 1')
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

  // The platform compares a typed text with a non-text value in its own way (#298 R4): the form
  // never guesses, so any typed text may be sent and an unchanged one is refused by the server.
  it.each([42, 1000000, 0.00001, false])('lets the server decide whether text typed for %j is a change', async value => {
    const form = mount(ExpertEditForm, {
      props: { spaceId: 'demo', release: release('rel-1', 1, value), slug: 'P1/f_wait', title: '等待期' },
      global: { plugins: [i18n()] },
    })
    await form.get('[data-reason]').setValue('核对')
    for (const typed of [String(value), '1e+06', '1e-05']) {
      await form.get('[data-value]').setValue(typed)
      expect(form.get('[data-submit]').attributes('disabled')).toBeUndefined()
    }
  })
})
