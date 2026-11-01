// @vitest-environment happy-dom
// PV-4b acceptance (protected, written by Claude): the navigation clusters a family, labels sale
// status, hides discontinued versions behind a switch while keeping the current entry, and the
// version page shows status, sale period, family and supersedes links in the same release
// (Spec docs/design/slices/PV-4b-读取侧.md §3). Strings are checked in zh-CN; every enterprise
// locale carries the same version keys.
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import enUS from './i18n/messages/en-US'
import jaJP from './i18n/messages/ja-JP'
import koKR from './i18n/messages/ko-KR'
import ruRU from './i18n/messages/ru-RU'
import zhMessages from './i18n/messages/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import EnterpriseEntity from './EnterpriseEntity.vue'
import EnterpriseNavigation from './EnterpriseNavigation.vue'
import ProductVersionMeta from './ProductVersionMeta.vue'
import { readRelease } from './enterpriseApi'
import { VERSION_NOW, versionRelease } from './__tests__/versionFixtures'

function render(component: any, props: Record<string, unknown>) {
  return mount(component, {
    props,
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub, CitationPanel: true, 't-drawer': true },
    },
  })
}

type Target = { params: { entityId: string } }
const entries = (view: ReturnType<typeof render>) =>
  view.findAll('[data-nav-entry]').map(entry => (entry.findComponent(RouterLinkStub).props('to') as Target).params.entityId)

beforeEach(() => { vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(VERSION_NOW) })
afterEach(() => { vi.useRealTimers(); vi.resetAllMocks() })

describe('navigation with versions', () => {
  it('clusters the family, labels status and hides the discontinued version by default', () => {
    const view = render(EnterpriseNavigation, { release: versionRelease(), spaceId: 'demo' })
    const families = view.findAll('[data-nav-family]')
    expect(families).toHaveLength(1)
    expect(families[0].text()).toContain('甲护理系列')
    expect(entries(view)).toEqual(['B1', 'V2', 'U1'])
    expect(view.find('[data-nav-entry] [data-sale-status="not_yet_on_sale"]').text()).toBe('未开售')
    expect(view.findAll('[data-sale-status="on_sale"]').map(badge => badge.text())).toEqual(['在售'])
    expect(view.findAll('[data-sale-status="discontinued"]')).toHaveLength(0)
    expect(view.find('[data-nav-discontinued]').text()).toContain('含停售（1）')
  })

  it('shows discontinued versions once included', async () => {
    const view = render(EnterpriseNavigation, { release: versionRelease(), spaceId: 'demo' })
    await view.find('[data-nav-discontinued] input').setValue(true)
    expect(entries(view)).toEqual(['B1', 'V2', 'V1', 'U1'])
    expect(view.find('[data-sale-status="discontinued"]').text()).toBe('停售')
  })

  it('keeps the current entry even when it is discontinued, and filtering obeys the switch', async () => {
    const current = render(EnterpriseNavigation, { release: versionRelease(), spaceId: 'demo', entityId: 'V1' })
    expect(entries(current)).toContain('V1')
    const view = render(EnterpriseNavigation, { release: versionRelease(), spaceId: 'demo' })
    await view.find('[data-nav-filter]').setValue('甲护理')
    expect(entries(view)).toEqual(['B1', 'V2'])
  })

  it('shows no switch when nothing is discontinued', () => {
    const base = versionRelease()
    const release = { ...base, members: base.members.filter(member => member.logical_slug !== 'entity/V1') }
    expect(render(EnterpriseNavigation, { release, spaceId: 'demo' }).find('[data-nav-discontinued]').exists()).toBe(false)
  })
})

describe('version page', () => {
  it('shows an on-sale version with its open period and its predecessor', () => {
    const view = render(ProductVersionMeta, { release: versionRelease(), spaceId: 'demo', entityId: 'V2' })
    expect(view.find('[data-sale-status]').text()).toBe('在售（据 2026-10-20 数据）')
    expect(view.find('[data-version-period]').text()).toContain('2024-04-23 起')
    expect(view.find('[data-version-family]').text()).toContain('甲护理系列')
    const link = view.find('[data-version-predecessor]').findComponent(RouterLinkStub)
    expect(link.props('to')).toEqual({ name: 'enterpriseEntity', params: { spaceId: 'demo', entityId: 'V1' }, query: { release: 'rel-v' } })
    expect(link.text()).toBe('甲护理保险')
    expect(view.find('[data-version-successor]').exists()).toBe(false)
  })

  it('shows a discontinued version with its closed period and its successor', () => {
    const view = render(ProductVersionMeta, { release: versionRelease(), spaceId: 'demo', entityId: 'V1' })
    expect(view.find('[data-sale-status]').text()).toBe('停售')
    expect(view.find('[data-version-period]').text()).toContain('2023-01-01 至 2024-04-23')
    expect((view.find('[data-version-successor]').findComponent(RouterLinkStub).props('to') as Target).params.entityId).toBe('V2')
  })

  it('renders nothing for an entity without version data', () => {
    const view = render(ProductVersionMeta, { release: versionRelease(), spaceId: 'demo', entityId: 'U1' })
    expect(view.find('[data-version-meta]').exists()).toBe(false)
  })

  it('appears on the entry page', async () => {
    vi.mocked(readRelease).mockResolvedValue(versionRelease())
    const view = render(EnterpriseEntity, { spaceId: 'demo', entityId: 'V1' })
    await flushPromises()
    expect(view.find('[data-version-meta]').exists()).toBe(true)
  })
})

describe('version strings', () => {
  const keys = (messages: any): string[] => {
    const out: string[] = []
    const walk = (value: any, path: string) => {
      if (value && typeof value === 'object') for (const [key, child] of Object.entries(value)) walk(child, path ? `${path}.${key}` : key)
      else out.push(path)
    }
    walk(messages?.enterpriseKnowledge?.version, '')
    return out.sort()
  }

  it('exist in every enterprise locale with the same keys', () => {
    const expected = keys(zhMessages)
    expect(expected).toEqual(expect.arrayContaining([
      'status.on_sale', 'status.discontinued', 'status.not_yet_on_sale', 'status.unknown', 'onSaleAsOf',
      'period', 'periodRange', 'periodFrom', 'periodUntil', 'family', 'predecessors', 'successors', 'includeDiscontinued',
    ]))
    for (const messages of [enUS, jaJP, koKR, ruRU]) expect(keys(messages)).toEqual(expected)
  })
})
