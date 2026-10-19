import { expect, it } from 'vitest'
import { claim, release } from './__tests__/s3eFixtures'
import { searchFields } from './releaseSearch'
const dataWith = (...claims: ReturnType<typeof claim>[]) => {
  const data = structuredClone(release())
  data.members = [...data.members.filter(member => member.kind !== 'claim'), ...claims]
  return data
}
const joined = (parts: { text: string }[]) => parts.map(part => part.text).join('')

it('maps normalized matches back to complete original characters without changing case or width', () => {
  const value = 'ＡＢ ﬃ Cafe\u0301 İ ΟΣ 😀'
  const data = dataWith(claim('M1', 'unicode', 'present', value))
  const hit = searchFields(data, 'ab ffi café i\u0307 ος 😀').hits[0]!
  expect(joined(hit.parts)).toBe(value)
  expect(hit.parts.filter(part => part.mark).map(part => part.text)).toEqual(['ＡＢ', 'ﬃ', 'Cafe\u0301', 'İ', 'ΟΣ', '😀'])
})

it('merges overlapping and repeated literal terms without duplicating snippet text', () => {
  const value = 'ababa a.b [x] ababa'
  const result = searchFields(dataWith(claim('M1', 'literal', 'present', value)), 'aba ab a.b [x] aba')
  expect(joined(result.hits[0]!.parts)).toBe(value)
  expect(result.hits[0]!.parts.filter(part => part.mark).map(part => part.text)).toEqual(['ababa', 'a.b', '[x]', 'ababa'])
})

it('joins array values, ignores empty values and does not match across the title/value boundary', () => {
  const data = dataWith(claim('M1', 'array', 'present', ['A\n\t B', '90日']),
    ...[null, '', '  ', [], ['', ' ']].map((value, index) => claim('M1', `empty_${index}`, 'present', value)),
    claim('M1', 'zero', 'present', 0), claim('M1', 'ends_a', 'present', 'b starts'))
  expect(joined(searchFields(data, 'array 90').hits[0]!.parts)).toBe('A B；90日')
  expect(searchFields(data, 'empty').total).toBe(0)
  expect(searchFields(data, '0').hits.some(hit => hit.fieldKey === 'zero')).toBe(true)
  expect(searchFields(data, 'ab').total).toBe(0)
})

it('keeps every Claim, uses each profile, and preserves member order for unknown fields without mutation', () => {
  const first = claim('M1', 'cooling_off_period', 'present', '命中一')
  const second = { ...claim('M1', 'cooling_off_period', 'present', '命中二'), logical_slug: 'M1/cooling_off_period/other' }
  const data = dataWith(claim('X1', 'loose', 'present', '命中'), claim('C1', 'cooling_off_period', 'present', '命中'),
    claim('M1', 'z_unknown', 'present', '命中'), claim('M1', 'waiting_period', 'present', '命中'),
    first, second, claim('M1', 'a_unknown', 'present', '命中'), claim('orphan', 'loose', 'present', '命中'))
  const profile = data.members.find(member => member.logical_slug === 'presentation/profile_critical')!
  const sections = profile.payload.sections as { fields: { short_title: string }[] }[]
  sections[0]!.fields[0]!.short_title = '本产品专用标题'
  const before = JSON.stringify(data)
  const result = searchFields(data, '命中')
  expect(result.hits.map(hit => hit.slug)).toEqual([
    first.logical_slug, second.logical_slug, 'M1/waiting_period', 'M1/z_unknown', 'M1/a_unknown',
    'C1/cooling_off_period', 'X1/loose', 'orphan/loose',
  ])
  expect(result.hits.find(hit => hit.entityId === 'C1')!.fieldTitle).toBe('本产品专用标题')
  expect(JSON.stringify(data)).toBe(before)
})

it('anchors on query-term order, clips complete characters and handles title-only matches', () => {
  const data = dataWith(claim('M1', 'anchor', 'present', `乙${'前'.repeat(45)}甲${'后'.repeat(45)}`),
    claim('M1', 'emoji', 'present', `${'😀'.repeat(21)}命中${'🌟'.repeat(41)}`),
    claim('M1', 'title_only', 'present', '长'.repeat(45)))
  expect(joined(searchFields(data, '甲 乙').hits[0]!.parts)).toBe(`…${'前'.repeat(20)}甲${'后'.repeat(40)}…`)
  expect(joined(searchFields(data, '命中').hits[0]!.parts)).toBe(`…${'😀'.repeat(20)}命中${'🌟'.repeat(40)}…`)
  const title = searchFields(data, 'title_only').hits[0]!
  expect(joined(title.parts)).toBe(`${'长'.repeat(40)}…`)
  expect(title.parts.some(part => part.mark)).toBe(false)
})

it('counts all hits independently of a bounded limit and treats normalized whitespace as empty', () => {
  const data = dataWith(...Array.from({ length: 53 }, (_, index) => claim('M1', `field_${index}`, 'present', '命中')))
  expect(searchFields(data, '命中').hits).toHaveLength(50)
  for (const limit of [0, -1, NaN]) expect(searchFields(data, '命中', limit)).toEqual({ hits: [], total: 53 })
  expect(searchFields(data, '命中', 1.9).hits).toHaveLength(1)
  expect(searchFields(data, '\u3000\n\t')).toEqual({ hits: [], total: 0 })
})
