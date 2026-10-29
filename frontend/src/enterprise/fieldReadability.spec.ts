// @vitest-environment happy-dom
// S3j acceptance (protected, written by Claude): field titles read like the free wiki's third-level
// headings, fields without an extracted value are grey in the navigation, and only the field the
// address points at is marked current (Spec docs/design/slices/S3j-字段标题与缺失字段标识.md §4).
import { readFileSync } from 'node:fs'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import EnterpriseEntity from './EnterpriseEntity.vue'
import EnterpriseNavigation from './EnterpriseNavigation.vue'
import { readRelease } from './enterpriseApi'
import { release } from './__tests__/s3eFixtures'

// Vitest blanks CSS imports, so the stylesheets are read from disk.
const css = (name: string) => readFileSync(new URL(name, import.meta.url), 'utf8')
const pageCss = css('./enterprisePage.css')
const navigationCss = css('./enterpriseNavigation.css')

const i18n = () => createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })

afterEach(() => { vi.resetAllMocks() })

// Declarations of every top-level or nested rule whose selector list names the selector, in order.
function rulesFor(css: string, selector: string): Record<string, string>[] {
  const rules: Record<string, string>[] = []
  for (const match of css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = match[1]!.split(',').map(part => part.trim())
    if (!selectors.some(part => part === selector || part.includes(selector))) continue
    const declarations: Record<string, string> = {}
    for (const line of match[2]!.split(';')) {
      const [name, ...value] = line.split(':')
      if (name && value.length) declarations[name.trim()] = value.join(':').trim()
    }
    rules.push(declarations)
  }
  return rules
}

const px = (value: string | undefined) => Number.parseFloat(value ?? '')

describe('field titles on a product page', () => {
  it('are third-level headings', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = mount(EnterpriseEntity, {
      props: { spaceId: 'demo', entityId: 'M2', releaseId: 'rel-9' },
      global: { plugins: [i18n()], stubs: { RouterLink: RouterLinkStub, CitationPanel: true, EnterpriseNavigation: true } },
    })
    await flushPromises()
    const titles = view.findAll('h3.ek-field__title').map(title => title.text())
    expect(titles).toEqual(expect.arrayContaining(['犹豫期', '等待期']))
  })

  it('use the free wiki third-level heading size, weight and colour, below the group title', () => {
    const exact = rulesFor(pageCss, '.ek-field__title').filter(rule => 'font-size' in rule || 'color' in rule)
    expect(exact.some(rule => rule['font-size'] === '17px' && rule['font-weight'] === '600'
      && rule.color === 'var(--td-text-color-primary)')).toBe(true)
    const sizes = rulesFor(pageCss, '.ek-field__title').map(rule => rule['font-size']).filter(Boolean)
    expect(sizes.every(size => px(size) >= 17)).toBe(true)
    const group = rulesFor(pageCss, '.ek-section__title').map(rule => px(rule['font-size'])).filter(size => !Number.isNaN(size))
    expect(group.length).toBeGreaterThan(0)
    expect(Math.min(...group)).toBeGreaterThan(17)
  })
})

async function navigation(entityId: string, address: string) {
  const blank = { template: '<div />' }
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: blank },
    { name: 'enterpriseSpace', path: '/enterprise/:spaceId', component: blank },
    { name: 'enterpriseConcept', path: '/enterprise/:spaceId/concepts/:conceptKey', component: blank },
    { name: 'enterpriseWikiPage', path: '/enterprise/:spaceId/wiki/:entityId/:pageType/:pageSlug', component: blank },
    { name: 'enterpriseEntity', path: '/enterprise/:spaceId/entities/:entityId', component: blank },
  ] })
  await router.push(address)
  const view = mount(EnterpriseNavigation, {
    props: { release: release(), spaceId: 'demo', entityId },
    global: { plugins: [router, i18n()] },
  })
  await flushPromises()
  return view
}

const fieldLinks = (view: Awaited<ReturnType<typeof navigation>>) => view.get('[data-nav-schema]').findAll('a')
const named = (view: Awaited<ReturnType<typeof navigation>>, title: string) => {
  const link = fieldLinks(view).find(candidate => candidate.text().startsWith(title))
  if (!link) throw new Error(`no field link for ${title}`)
  return link
}

describe('fields in the navigation', () => {
  it('grey out a field whose value was not extracted, in words as well as colour', async () => {
    const view = await navigation('M2', '/enterprise/demo/entities/M2?release=rel-9')
    const missing = named(view, '等待期')
    expect(missing.attributes('data-field-missing')).toBeDefined()
    expect(missing.text()).toContain('材料未提及')
    expect(missing.attributes('title')).toBe('等待期（材料未提及）')
    expect(named(view, '犹豫期').attributes('data-field-missing')).toBeUndefined()
  })

  it('does not treat an explicit "the material has none" as missing', async () => {
    const view = await navigation('C1', '/enterprise/demo/entities/C1?release=rel-9')
    expect(named(view, '宽限期').attributes('data-field-missing')).toBeUndefined()
  })

  it('marks no field as current on the product page itself', async () => {
    const view = await navigation('M2', '/enterprise/demo/entities/M2?release=rel-9')
    expect(fieldLinks(view).filter(link => link.attributes('aria-current') !== undefined).map(link => link.text()))
      .toEqual([])
  })

  it('marks only the field the address points at, as a location', async () => {
    const view = await navigation('M2', '/enterprise/demo/entities/M2?release=rel-9#waiting_period')
    const current = fieldLinks(view).filter(link => link.attributes('aria-current') !== undefined)
    expect(current.map(link => [link.text().slice(0, 3), link.attributes('aria-current')])).toEqual([['等待期', 'location']])
  })

  it('styles a missing field with the placeholder colour', () => {
    const rules = rulesFor(navigationCss, '[data-field-missing]')
    expect(rules.some(rule => rule.color === 'var(--td-text-color-placeholder)')).toBe(true)
  })
})
