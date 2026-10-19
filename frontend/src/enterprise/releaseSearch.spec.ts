// S3h-1 acceptance (protected, written by Claude): full-text search over the field values of one
// release (Spec docs/design/slices/S3h-全文搜索与本版变化.md §2.1). Synthetic data only.
import { describe, expect, it } from 'vitest'
import { claim, release } from './__tests__/s3eFixtures'
import { searchFields } from './releaseSearch'
import type { Release } from './enterpriseApi'

const slugs = (result: ReturnType<typeof searchFields>) => result.hits.map(hit => hit.slug)
const joined = (hit: { parts: { text: string }[] }) => hit.parts.map(part => part.text).join('')
const marks = (hit: { parts: { text: string; mark: boolean }[] }) => hit.parts.filter(part => part.mark).map(part => part.text)

function withClaims(...extra: ReturnType<typeof claim>[]): Release {
  const data = structuredClone(release())
  data.members.push(...extra)
  return data
}

describe('field search', () => {
  it('finds present values, with the entry name and the profile field title', () => {
    const result = searchFields(release(), '15日')
    expect(slugs(result)).toEqual(['M1/cooling_off_period', 'M2/cooling_off_period'])
    expect(result.total).toBe(2)
    expect(result.hits.map(hit => [hit.entityId, hit.name, hit.fieldKey, hit.fieldTitle]))
      .toEqual([['M1', '甲医疗', 'cooling_off_period', '犹豫期'], ['M2', '乙医疗', 'cooling_off_period', '犹豫期']])
  })

  it('requires every term, in the field title or the value', () => {
    expect(slugs(searchFields(release(), '犹豫期 20日'))).toEqual(['C1/cooling_off_period'])
    expect(slugs(searchFields(release(), '宽限期 20日'))).toEqual([])
  })

  it('never searches unknown or explicitly absent claims', () => {
    expect(slugs(searchFields(release(), '60日'))).toEqual(['M1/premium_grace_period'])
    expect(slugs(searchFields(release(), '宽限期'))).toEqual(['M1/premium_grace_period']) // C1's is absent_explicitly
  })

  it('matches after NFKC and case folding', () => {
    expect(slugs(searchFields(release(), '１５日'))).toEqual(['M1/cooling_off_period', 'M2/cooling_off_period'])
    const data = withClaims(claim('M1', 'icu_rule', 'present', '入住ICU病房需提供证明。'))
    expect(slugs(searchFields(data, 'icu'))).toEqual(['M1/icu_rule'])
    expect(searchFields(data, 'icu').hits[0]!.fieldTitle).toBe('icu_rule') // no profile title: the predicate
  })

  it('cuts the snippet around the first match and marks every term occurrence in it', () => {
    const [far] = searchFields(release(), '损失').hits
    expect(joined(far!)).toBe('…犹豫期解除合同的，退还现金价值，并可能有损失。')
    expect(marks(far!)).toEqual(['损失'])
    const [near] = searchFields(release(), '退还').hits.filter(hit => hit.entityId === 'C1')
    expect(joined(near!)).toBe('自签收之日起20日，期间解除合同的，退还全部保费；超过犹豫期解除合同的，退还现金价值，并可能有损失。')
    expect(marks(near!)).toEqual(['退还', '退还'])
    const long = withClaims(claim('M1', 'long_rule', 'present', `开头命中词${'乙'.repeat(60)}`))
    expect(joined(searchFields(long, '命中词').hits[0]!)).toBe(`开头命中词${'乙'.repeat(40)}…`)
    const spaced = withClaims(claim('M1', 'spaced_rule', 'present', 'A\n\n  B 命中'))
    expect(joined(searchFields(spaced, '命中').hits[0]!)).toBe('A B 命中')
  })

  it('reports the total and returns at most the limit', () => {
    const result = searchFields(release(), '日', 2)
    expect(result.hits).toHaveLength(2)
    expect(result.total).toBe(5)
    expect(searchFields(release(), '   ')).toEqual({ hits: [], total: 0 })
  })

  it('orders entries by navigation group, then fields by the profile order', () => {
    const data = structuredClone(release())
    const entities = data.members.filter(member => member.kind === 'entity')
    data.members = [...entities.reverse(), ...data.members.filter(member => member.kind !== 'entity')]
    expect(slugs(searchFields(data, '日'))).toEqual([
      'M2/cooling_off_period', // within one group, entry member order (reversed here)
      'M1/cooling_off_period', 'M1/premium_grace_period', 'M1/waiting_period',
      'C1/cooling_off_period',
    ])
  })
})
