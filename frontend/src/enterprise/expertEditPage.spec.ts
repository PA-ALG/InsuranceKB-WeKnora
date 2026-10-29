// @vitest-environment happy-dom
// S9b acceptance (protected, written by Claude): on the entity page an administrator gets a 修改
// button on every field and others get none; a published edit switches the page to the new
// release and says so; a stale edit goes back to the Active release
// (Spec docs/design/slices/S9b-专家编辑界面.md §2.2, §2.4).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { createI18n } from 'vue-i18n'
import { routeLocationKey, routerKey } from 'vue-router'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

const access = vi.hoisted(() => ({ role: 'admin' }))
vi.mock('@/stores/auth', () => {
  const level: Record<string, number> = { viewer: 10, contributor: 20, admin: 30, owner: 40 }
  return { useAuthStore: () => ({ hasRole: (min: string) => (level[access.role] ?? 0) >= level[min] }) }
})
vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import CitationPanel from './CitationPanel.vue'
import EnterpriseEntity from './EnterpriseEntity.vue'
import ExpertEditForm from './ExpertEditForm.vue'
import { readRelease, type Release } from './enterpriseApi'

function claim(slug: string, value: string, origin = 'SOURCE_SUPPORTED') {
  return {
    kind: 'claim', logical_slug: slug, member_digest: 'd'.repeat(64), access_scope: 'space',
    payload: { subject_ref: 'P1', predicate: slug.split('/')[1], state: 'present', value, origin, evidence: [{}] },
  }
}

const release = (id: string, epoch: number): Release => ({
  id, epoch,
  members: [claim('P1/f_wait', '90日'), claim('P1/f_grace', '60日'), claim('P1/f_note', '说明', 'MODEL_GENERATED')],
})

let replace: ReturnType<typeof vi.fn>
let route: { query: Record<string, string>; hash: string }

function page(releaseId = 'rel-1') {
  return mount(EnterpriseEntity, {
    props: { spaceId: 'demo', entityId: 'P1', releaseId },
    global: {
      plugins: [createPinia(), createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub, CitationPanel: true, ExpertEditForm: true, EnterpriseNavigation: true },
      provide: {
        [routerKey as symbol]: { replace, afterEach: () => () => undefined },
        [routeLocationKey as symbol]: route,
      },
    },
  })
}

beforeEach(() => {
  access.role = 'admin'
  replace = vi.fn(() => Promise.resolve())
  route = reactive({ query: { release: 'rel-1', tab: 'fields' }, hash: '#f_wait' })
  vi.mocked(readRelease).mockImplementation((_space, id) => Promise.resolve(release(id ?? 'rel-1', id === 'rel-2' ? 2 : 1)))
})
afterEach(() => { vi.resetAllMocks() })

describe('who sees 修改', () => {
  it.each(['admin', 'owner'])('%s gets one on every field', async role => {
    access.role = role
    const view = page()
    await flushPromises()
    const buttons = view.findAll('[data-expert-edit]')
    expect(buttons).toHaveLength(3)
    expect(buttons.map(button => button.text())).toEqual(['修改', '修改', '修改'])
  })

  it.each(['contributor', 'viewer'])('%s gets none', async role => {
    access.role = role
    const view = page()
    await flushPromises()
    expect(view.find('[data-expert-edit]').exists()).toBe(false)
  })
})

describe('editing a field', () => {
  it('opens the form for that field on the shown release, closing an open source', async () => {
    const view = page()
    await flushPromises()
    const field = view.get('[data-field="P1/f_grace"]')
    await field.get('.ek-source').trigger('click')
    expect(view.findComponent(CitationPanel).exists()).toBe(true)
    await field.get('[data-expert-edit]').trigger('click')
    expect(view.findComponent(CitationPanel).exists()).toBe(false)
    const form = view.getComponent(ExpertEditForm)
    expect(form.props()).toMatchObject({ spaceId: 'demo', slug: 'P1/f_grace' })
    expect((form.props('release') as Release).id).toBe('rel-1')
  })

  it('switches to the published release, keeping the other query and the anchor, and says so', async () => {
    const view = page()
    await flushPromises()
    await view.get('[data-field="P1/f_wait"] [data-expert-edit]').trigger('click')
    view.getComponent(ExpertEditForm).vm.$emit('published', { releaseId: 'rel-2', epoch: 2 })
    await flushPromises()
    expect(view.findComponent(ExpertEditForm).exists()).toBe(false)
    expect(replace).toHaveBeenCalledTimes(1)
    expect(replace.mock.calls[0][0]).toMatchObject({ query: { release: 'rel-2', tab: 'fields' }, hash: '#f_wait' })

    await view.setProps({ releaseId: 'rel-2' })
    await flushPromises()
    expect(view.get('[data-expert-notice]').text()).toContain('已保存，已发布为第 2 版')
    expect(view.get('[data-expert-notice]').attributes('role')).toBe('status')

    await view.setProps({ entityId: 'P2' })
    await flushPromises()
    expect(view.find('[data-expert-notice]').exists()).toBe(false)
  })

  it('goes back to the Active release when the edit was stale', async () => {
    const view = page()
    await flushPromises()
    await view.get('[data-field="P1/f_wait"] [data-expert-edit]').trigger('click')
    view.getComponent(ExpertEditForm).vm.$emit('reload')
    await flushPromises()
    expect(view.findComponent(ExpertEditForm).exists()).toBe(false)
    expect(replace).toHaveBeenCalledTimes(1)
    const target = replace.mock.calls[0][0] as { query: Record<string, string>; hash: string }
    expect(target.query).toEqual({ tab: 'fields' })
    expect(target.hash).toBe('#f_wait')
  })
})
