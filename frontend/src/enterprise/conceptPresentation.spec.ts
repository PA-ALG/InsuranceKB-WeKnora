// @vitest-environment happy-dom
// Regression coverage for concept definition provenance and navigation-group ordering.
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import { claim, member, release } from './__tests__/s3eFixtures'
import { conceptView } from './conceptView'
import EnterpriseConcept from './EnterpriseConcept.vue'
import { readRelease, type Release } from './enterpriseApi'

vi.mock('./enterpriseApi', async original => ({
  ...(await original<typeof import('./enterpriseApi')>()), readRelease: vi.fn(),
}))

const key = 'cooling_off_period'
const readerDefinition = '供读者了解合同解除规则的一段期间。'
const profileDefinition = '投保人收到合同后可解除合同并退还保费的期间。'

function publishedDefinition(value: string): Release {
  const result = structuredClone(release())
  result.members.find(item => item.kind === 'concept')!.payload!.definition = value
  return result
}

function interleaved(): Release {
  const result = structuredClone(release())
  const entities = new Map(result.members.filter(item => item.kind === 'entity')
    .map(item => [item.payload!.entity_id as string, item]))
  result.members = [
    ...['X1', 'C1', 'M2', 'M1'].map(id => entities.get(id)!),
    ...result.members.filter(item => item.kind !== 'entity'),
  ]
  return result
}

async function page(result: Release) {
  vi.mocked(readRelease).mockResolvedValue(result)
  const view = mount(EnterpriseConcept, {
    props: { spaceId: 'demo', conceptKey: key, releaseId: result.id },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub },
    },
  })
  await flushPromises()
  return view
}

afterEach(() => { vi.resetAllMocks() })

describe('concept definition provenance', () => {
  it('prefers the published reader definition over profile extraction instructions', () => {
    const result = publishedDefinition(readerDefinition)
    const profile = result.members.find(item => item.kind === 'presentation_profile')!
    const sections = profile.payload!.sections as { fields: { description: string }[] }[]
    sections[0].fields[0].description = '只允许从正式条款中抽取，并保留起算方式。'
    expect(conceptView(result, key)!.definition).toBe(readerDefinition)
  })

  it.each(['', '   '])('shows no definition when the published definition is blank (%j), never the profile description', value => {
    expect(conceptView(publishedDefinition(value), key)!.definition).toBe('')
  })

  it('labels the reader definition as model-generated even without an explanation', async () => {
    const result = publishedDefinition(readerDefinition)
    result.members.find(item => item.kind === 'concept')!.payload!.explanation = ''
    const view = await page(result)
    const definition = view.get('[data-concept-definition]')
    expect(definition.text()).toContain(readerDefinition)
    expect(definition.text()).not.toContain(profileDefinition)
    expect(definition.text()).toContain('模型补充')
    expect(definition.text().indexOf('模型补充')).toBeLessThan(definition.text().indexOf(readerDefinition))
    expect(view.find('[data-concept-explanation]').exists()).toBe(false)
    view.unmount()
  })

  it('shows no definition when no concept was published (S3e-4)', async () => {
    const result = release({ concept: false })
    expect(conceptView(result, key)!.definition).toBe('')
    const view = await page(result)
    expect(view.find('[data-concept-definition]').exists()).toBe(false)
    expect(view.text()).not.toContain(profileDefinition)
    expect(view.findAll('[data-concept-row]')).toHaveLength(4)
    view.unmount()
  })
})

describe('concept comparison order', () => {
  it('collects interleaved entries by navigation group, preserving member order within each group', () => {
    expect(conceptView(interleaved(), key)!.rows.map(row => row.entityId)).toEqual(['M2', 'M1', 'C1', 'X1'])
  })

  it('puts all unmatched entries after matched domains and keeps every applicability claim', () => {
    const result = interleaved()
    result.members.unshift(
      member('entity', 'entity/U1', { entity_id: 'U1', entity_type: 'other_domain', names: ['未归领域'], classification_labels: [] }),
      member('entity', 'entity/S1', { entity_id: 'S1', entity_type: 'service_benefit', names: ['服务'], classification_labels: ['family_doctor'] }),
    )
    result.members.push(
      claim('U1', key, 'unknown', null, 0), claim('S1', key, 'present', '服务规定。'),
      { ...claim('M2', key, 'present', '另一适用范围。'), logical_slug: 'M2/another-scope' },
    )
    expect(conceptView(result, key)!.rows.map(row => row.slug)).toEqual([
      `M2/${key}`, 'M2/another-scope', `M1/${key}`, `C1/${key}`, `S1/${key}`, `U1/${key}`, `X1/${key}`,
    ])
  })

  it('retains member order when an older release has no navigation', () => {
    const result = interleaved()
    result.members = result.members.filter(item => item.kind !== 'navigation')
    expect(conceptView(result, key)!.rows.map(row => row.entityId)).toEqual(['X1', 'C1', 'M2', 'M1'])
  })
})
