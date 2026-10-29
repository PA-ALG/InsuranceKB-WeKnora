// @vitest-environment happy-dom
// S3f-2b acceptance (protected, written by Claude): the Space home is a directory — a named title,
// a search over products and concepts, a product overview with one short value per field, and the
// most common concepts — and the navigation lists one line per product
// (Spec docs/design/slices/S3f2-空间首页与导航.md §2.2–§2.3).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import EnterpriseSpace from './EnterpriseSpace.vue'
import { readRelease, type Release, type ReleaseMember } from './enterpriseApi'

function member(kind: string, slug: string, payload: Record<string, unknown>): ReleaseMember {
  return { kind, logical_slug: slug, payload, member_digest: 'd'.repeat(64), access_scope: 'space' }
}

function claim(subject: string, predicate: string, state: string, value: string | null): ReleaseMember {
  return member('claim', `${subject}/${predicate}`, {
    subject_ref: subject, predicate, state, value, origin: 'SOURCE_SUPPORTED', evidence: state === 'unknown' ? [] : [{ quote: 'q' }],
  })
}

const FIELDS = [
  { field_key: 'entry_age_range', short_title: '投保年龄' },
  { field_key: 'coverage_period', short_title: '保险期间' },
  { field_key: 'waiting_period', short_title: '等待期' },
  { field_key: 'cooling_off_period', short_title: '犹豫期' },
]

function release(navigationName: string | null = '保险产品知识库'): Release {
  const navigation: Record<string, unknown> = {
    navigation_id: 'enterprise', navigation_version: 'v2',
    overview_fields: ['entry_age_range', 'coverage_period', 'waiting_period', 'cooling_off_period'],
    domains: [{
      domain_key: 'product', display_name: '产品库', entity_types: ['insurance_product'],
      groups: [
        { group_key: 'pack_medical', display_name: '医疗险', classification_labels: ['medical'] },
        { group_key: 'pack_term', display_name: '定期寿险', classification_labels: ['term'] },
        { group_key: 'pack_critical', display_name: '重疾险', classification_labels: ['critical'] },
      ],
    }],
  }
  if (navigationName) navigation.display_name = navigationName
  return {
    id: 'rel-29',
    epoch: 29,
    members: [
      member('navigation', 'navigation/enterprise', navigation),
      ...['medical', 'critical'].map(label => member('presentation_profile', `presentation/${label}`, {
        profile_id: label, display_name: label === 'medical' ? '医疗险' : '重疾险', classification_labels: [label],
        sections: [{ section_key: 'terms', display_name: '条款', fields: FIELDS }],
      })),
      member('entity', 'entity/M1', { entity_id: 'M1', entity_type: 'insurance_product', names: ['甲医疗保险'], classification_labels: ['medical'] }),
      member('entity', 'entity/M2', { entity_id: 'M2', entity_type: 'insurance_product', names: ['乙医疗保险（费率可调）长期版本名称很长'], classification_labels: ['medical'] }),
      member('entity', 'entity/C1', { entity_id: 'C1', entity_type: 'insurance_product', names: ['丙重疾保险'], classification_labels: ['critical'] }),
      claim('M1', 'entry_age_range', 'present', '0周岁（须出生满28日）至70周岁，续保可至100周岁。'),
      claim('M1', 'coverage_period', 'present', '本合同的保险期间为1年，自本合同生效日零时起至期满日二十四时止的期间届满。'),
      claim('M1', 'waiting_period', 'present', '自本合同生效之日起30日内为等待期。'),
      claim('M1', 'cooling_off_period', 'present', '自您签收本合同之日起15日内为犹豫期。'),
      claim('M2', 'entry_age_range', 'unknown', null),
      claim('M2', 'coverage_period', 'present', '1. 20年长期保障不中断；2. 保证续保。'),
      claim('M2', 'waiting_period', 'present', '自本合同生效之日起90日内为等待期。'),
      claim('M2', 'cooling_off_period', 'present', '自您签收本合同之日起20日内为犹豫期。'),
      claim('C1', 'coverage_period', 'present', '被保险人终身。'),
      claim('C1', 'waiting_period', 'absent_explicitly', null),
      claim('C1', 'cooling_off_period', 'present', '自您签收本合同之日起20日内为犹豫期。'),
      member('concept', 'concept/cooling_off_period', { concept_key: 'cooling_off_period', title: '犹豫期', definition: '签收后可解除合同的期间。' }),
    ],
  }
}

function page() {
  return mount(EnterpriseSpace, {
    props: { spaceId: 'demo' },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub },
    },
  })
}

function cell(view: ReturnType<typeof page>, entity: string, field: string) {
  return view.get(`[data-overview-row="${entity}"] [data-overview-cell="${field}"]`)
}

afterEach(() => { vi.resetAllMocks() })

describe('Space home', () => {
  it('is titled by the Space name, with its version and what it holds', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    expect(view.get('[data-space-title]').text()).toBe('保险产品知识库')
    expect(view.get('[data-space-version]').text()).toBe('版本 29')
    const counts = view.get('[data-space-counts]').text()
    expect(counts).toContain('3 款产品')
    expect(counts).toContain('3 个跨产品概念') // coverage_period, waiting_period, cooling_off_period
    expect(view.find('h1').text()).not.toContain('demo')
  })

  it('falls back to a plain title without a Space name', async () => {
    vi.mocked(readRelease).mockResolvedValue(release(null))
    const view = page()
    await flushPromises()
    expect(view.get('[data-space-title]').text()).toBe('企业知识')
  })

  it('lists products by navigation group with one short value per overview field', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    expect(view.findAll('[data-overview-group]').map(group => group.attributes('data-overview-group'))).toEqual(['pack_medical', 'pack_critical'])
    expect(view.get('[data-overview-group="pack_medical"]').text()).toContain('2')
    expect(view.findAll('[data-overview-column]').map(column => column.text())).toEqual(['产品', '投保年龄', '保险期间', '等待期', '犹豫期'])

    expect(cell(view, 'M1', 'cooling_off_period').text()).toBe('15日') // the only number with a unit
    expect(cell(view, 'M1', 'cooling_off_period').attributes('title')).toBe('自您签收本合同之日起15日内为犹豫期。')
    expect(cell(view, 'M1', 'entry_age_range').text()).toBe('0周岁（须出生满28日）至70周岁') // several numbers: first sentence
    expect(cell(view, 'M1', 'coverage_period').text()).toBe('1年') // one number in the first clause
    expect(cell(view, 'M2', 'coverage_period').text()).toBe('20年') // a list number is not part of the value
    expect(cell(view, 'M2', 'entry_age_range').text()).toBe('—')
    expect(cell(view, 'C1', 'waiting_period').text()).toBe('无')
    expect(cell(view, 'C1', 'entry_age_range').text()).toBe('—') // no claim at all
    expect(cell(view, 'C1', 'coverage_period').text()).toBe('被保险人终身') // no number: the first clause

    const link = view.get('[data-overview-row="C1"]').findComponent(RouterLinkStub)
    expect(link.props('to')).toEqual({ name: 'enterpriseEntity', params: { spaceId: 'demo', entityId: 'C1' }, query: { release: 'rel-29' } })
  })

  it('filters products and concepts as one types', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    await view.get('[data-space-search] input').setValue('乙医疗')
    expect(view.findAll('[data-overview-row]').map(row => row.attributes('data-overview-row'))).toEqual(['M2'])
    await view.get('[data-space-search] input').setValue('犹豫')
    expect(view.findAll('[data-overview-row]')).toHaveLength(0)
    expect(view.findAll('[data-common-concept]').map(link => link.text())).toEqual(['犹豫期'])
  })

  it('offers the most stated concepts first, then all of them', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    // cooling_off_period: 3 products, waiting_period: 3, coverage_period: 3, entry_age_range: 1 (not a concept).
    // Ties keep the profile's field order.
    expect(view.findAll('[data-common-concept]').map(link => link.text())).toEqual(['保险期间', '等待期', '犹豫期'])
    expect(view.get('[data-all-concepts]').text()).toContain('全部 3 个')
  })

  it('lists one line per product in the navigation, full name on hover, no item counts', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    const entries = view.findAll('[data-nav-entry]')
    expect(entries).toHaveLength(3)
    const long = entries.find(entry => entry.text().includes('乙医疗'))!
    expect(long.get('[title]').attributes('title')).toBe('乙医疗保险（费率可调）长期版本名称很长')
    expect(entries.every(entry => !/\d+\s*项/.test(entry.text()))).toBe(true)
    expect(view.findAll('[data-nav-group]').map(group => group.text())).not.toContainEqual(expect.stringContaining('定期寿险'))
  })
})
