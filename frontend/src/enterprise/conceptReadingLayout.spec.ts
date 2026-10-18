// @vitest-environment happy-dom
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/i18n/locales/zh-CN'
import { release } from './__tests__/s3eFixtures'
import EnterpriseConcept from './EnterpriseConcept.vue'
import { readRelease, type Release } from './enterpriseApi'

vi.mock('./enterpriseApi', async original => ({
  ...(await original<typeof import('./enterpriseApi')>()), readRelease: vi.fn(),
}))

async function page(data: Release) {
  vi.mocked(readRelease).mockResolvedValue(data)
  const view = mount(EnterpriseConcept, {
    props: { spaceId: 'demo', conceptKey: 'cooling_off_period', releaseId: data.id },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub, EnterpriseNavigation: true },
    },
  })
  await flushPromises()
  return view
}

afterEach(() => vi.resetAllMocks())

const combinations = [true, false].flatMap(generated => [true, false].flatMap(explanation =>
  [true, false].flatMap(statements => [true, false].map(stale => ({ generated, explanation, statements, stale }))),
))

describe('one model block on the concept page', () => {
  it.each(combinations)('preserves provenance and content: %j', async options => {
    const data = structuredClone(release({ changedDigest: options.stale }))
    const concept = data.members.find(member => member.kind === 'concept')!.payload
    concept.definition = options.generated ? '面向读者的定义。' : ''
    if (!options.explanation) concept.explanation = ''
    if (!options.statements) concept.statements = []
    const view = await page(data)
    const blocks = view.findAll('.ek-section--generated')
    expect(blocks).toHaveLength(1)
    const block = blocks[0]!
    const definition = view.get('[data-concept-definition]')
    expect(view.findAll('[data-concept-definition]')).toHaveLength(1)
    expect(block.element.contains(definition.element)).toBe(options.generated)
    expect(definition.text()).toContain(options.generated ? '面向读者的定义。' : '投保人收到合同后可解除合同并退还保费的期间。')
    expect(definition.text().includes('模型补充')).toBe(options.generated)
    expect(definition.find('.ek-concept-definition').exists()).toBe(true)
    expect(block.text()).toContain('模型补充')
    expect(view.find('[data-concept-explanation]').exists()).toBe(options.explanation)
    if (options.explanation) {
      expect(block.get('[data-concept-explanation]').text()).toContain('冷静期')
    }
    expect(block.get('[data-concept-summary]').text()).toContain('模型汇总（依据各产品原文）')
    expect(block.findAll('[data-concept-statement]')).toHaveLength(options.statements ? 2 : 0)
    if (options.statements) {
      const links = block.get('[data-concept-statement]').findAllComponents(RouterLinkStub)
      expect(links.map((link: { props: (key: 'to') => unknown }) => link.props('to'))).toEqual(['M1', 'M2'].map(entityId => ({
        name: 'enterpriseEntity', params: { spaceId: 'demo', entityId },
        query: { release: 'rel-9' }, hash: '#cooling_off_period',
      })))
    }
    expect(view.find('[data-concept-stale]').exists()).toBe(options.stale)
    if (options.stale) expect(block.element.firstElementChild).toBe(view.get('[data-concept-stale]').element)
    expect(view.findAll('[data-concept-row]')).toHaveLength(4)
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-9']])
    view.unmount()
  })

  it.each([true, false])('has no model block without published model content (schema definition: %s)', async hasDefinition => {
    const data = structuredClone(release({ concept: false }))
    if (!hasDefinition) {
      for (const member of data.members.filter(member => member.kind === 'presentation_profile')) {
        const sections = member.payload.sections as { fields: { description: string }[] }[]
        for (const section of sections) for (const field of section.fields) field.description = ''
      }
    }
    const view = await page(data)
    expect(view.find('.ek-section--generated').exists()).toBe(false)
    expect(view.find('[data-concept-definition]').exists()).toBe(hasDefinition)
    expect(view.find('[data-concept-summary]').exists()).toBe(false)
    expect(view.find('[data-concept-explanation]').exists()).toBe(false)
    expect(view.find('[data-concept-stale]').exists()).toBe(false)
    expect(view.findAll('[data-concept-row]')).toHaveLength(4)
    view.unmount()
  })
})
