// @vitest-environment happy-dom
// S3e-2 acceptance (protected, written by Claude): the Space page is a navigation tree plus a
// concept list over the release it read; the concept page shows the definition, the labelled model
// explanation and summary with product links, the stale notice and one clickable row per entry; an
// entry page links each concept field to its concept page and anchors every field
// (Spec docs/design/slices/S3e-企业知识导航与概念页.md §3).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import EnterpriseConcept from './EnterpriseConcept.vue'
import EnterpriseEntity from './EnterpriseEntity.vue'
import EnterpriseSpace from './EnterpriseSpace.vue'
import { EnterpriseError, readRelease } from './enterpriseApi'
import { release } from './__tests__/s3eFixtures'

function page(component: any, props: Record<string, unknown>) {
  return mount(component, {
    props,
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub, CitationPanel: true },
    },
  })
}

function targets(view: ReturnType<typeof page>, selector: string) {
  return view.findAll(selector).map(item => item.findComponent(RouterLinkStub).props('to'))
}

afterEach(() => { vi.resetAllMocks() })

describe('Space page navigation', () => {
  it('shows domains, groups with counts, entries and concepts of the release it read', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page(EnterpriseSpace, { spaceId: 'demo' })
    await flushPromises()
    expect(view.findAll('[data-nav-domain]').map(domain => domain.text())).toEqual([expect.stringContaining('产品库')])
    const groups = view.findAll('[data-nav-group]').map(group => group.text())
    expect(groups).toEqual([
      expect.stringContaining('医疗险'),
      expect.stringContaining('重疾险'),
      expect.stringContaining('其他'),
    ])
    expect(groups[0]).toContain('2')
    expect(targets(view, '[data-nav-entry]')).toEqual(
      ['M1', 'M2', 'C1', 'X1'].map(entityId => ({
        name: 'enterpriseEntity', params: { spaceId: 'demo', entityId }, query: { release: 'rel-9' },
      })),
    )
    expect(targets(view, '[data-nav-concept]')).toEqual(
      ['cooling_off_period', 'premium_grace_period'].map(conceptKey => ({
        name: 'enterpriseConcept', params: { spaceId: 'demo', conceptKey }, query: { release: 'rel-9' },
      })),
    )
  })
})

describe('concept page', () => {
  it('shows the definition, the labelled model text and one linked row per entry', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page(EnterpriseConcept, { spaceId: 'demo', conceptKey: 'cooling_off_period', releaseId: 'rel-9' })
    await flushPromises()
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-9']])
    expect(view.text()).toContain('犹豫期')
    expect(view.get('[data-concept-definition]').text()).toContain('投保人收到合同后可解除合同并退还保费的期间。')
    const explanation = view.get('[data-concept-explanation]')
    expect(explanation.text()).toContain('冷静期')
    expect(explanation.text()).toContain('模型补充')
    expect(view.get('[data-concept-summary]').text()).toContain('模型汇总（依据各产品原文）')
    const statements = view.findAll('[data-concept-statement]')
    expect(statements).toHaveLength(2)
    expect(statements[0].findAllComponents(RouterLinkStub).map((link: { props: (key: 'to') => unknown }) => link.props('to'))).toEqual(
      ['M1', 'M2'].map(entityId => ({
        name: 'enterpriseEntity', params: { spaceId: 'demo', entityId }, query: { release: 'rel-9' }, hash: '#cooling_off_period',
      })),
    )
    expect(view.find('[data-concept-stale]').exists()).toBe(false)
    const rows = view.findAll('[data-concept-row]')
    expect(rows).toHaveLength(4)
    expect(rows[1].text()).toContain('乙医疗')
    expect(rows[1].text()).toContain('期间；退费；手续…')
    expect(rows[3].text()).toContain('材料未提及')
    expect(rows[1].findComponent(RouterLinkStub).props('to')).toEqual({
      name: 'enterpriseEntity', params: { spaceId: 'demo', entityId: 'M2' }, query: { release: 'rel-9' }, hash: '#cooling_off_period',
    })
    expect(targets(view, '[data-concept-related]')).toEqual([
      { name: 'enterpriseConcept', params: { spaceId: 'demo', conceptKey: 'premium_grace_period' }, query: { release: 'rel-9' } },
    ])
  })

  it('says when the summary rests on claims changed since', async () => {
    vi.mocked(readRelease).mockResolvedValue(release({ changedDigest: true }))
    const view = page(EnterpriseConcept, { spaceId: 'demo', conceptKey: 'cooling_off_period', releaseId: 'rel-9' })
    await flushPromises()
    expect(view.get('[data-concept-stale]').text()).toContain('汇总基于较早版本')
  })

  it('shows the table without model text when no summary was published', async () => {
    vi.mocked(readRelease).mockResolvedValue(release({ concept: false }))
    const view = page(EnterpriseConcept, { spaceId: 'demo', conceptKey: 'cooling_off_period', releaseId: 'rel-9' })
    await flushPromises()
    expect(view.find('[data-concept-explanation]').exists()).toBe(false)
    expect(view.findAll('[data-concept-row]')).toHaveLength(4)
  })

  it('says when the release holds no such concept and retries after a failure', async () => {
    vi.mocked(readRelease).mockResolvedValueOnce(release())
    const missing = page(EnterpriseConcept, { spaceId: 'demo', conceptKey: 'waiting_period', releaseId: 'rel-9' })
    await flushPromises()
    expect(missing.text()).toContain('该版本中没有这个概念')

    vi.mocked(readRelease).mockRejectedValueOnce(new EnterpriseError('REQUEST_FAILED')).mockResolvedValueOnce(release())
    const failing = page(EnterpriseConcept, { spaceId: 'demo', conceptKey: 'cooling_off_period', releaseId: 'rel-9' })
    await flushPromises()
    expect(failing.get('[role="alert"]').text()).toContain('概念加载失败')
    await failing.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(failing.findAll('[data-concept-row]')).toHaveLength(4)
  })
})

describe('entry page links', () => {
  it('links concept fields to their concept page and anchors every field', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page(EnterpriseEntity, { spaceId: 'demo', entityId: 'M1', releaseId: 'rel-9' })
    await flushPromises()
    const cooling = view.get('[data-field="M1/cooling_off_period"]')
    expect(cooling.attributes('id')).toBe('cooling_off_period')
    expect(cooling.get('.ek-field__title').findComponent(RouterLinkStub).props('to')).toEqual({
      name: 'enterpriseConcept', params: { spaceId: 'demo', conceptKey: 'cooling_off_period' }, query: { release: 'rel-9' },
    })
    const waiting = view.get('[data-field="M1/waiting_period"]')
    expect(waiting.attributes('id')).toBe('waiting_period')
    expect(waiting.get('.ek-field__title').findComponent(RouterLinkStub).exists()).toBe(false)
  })
})
