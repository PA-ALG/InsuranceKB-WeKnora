import { expect, it } from 'vitest'
import { baseRelease, currentRelease } from './__tests__/changesFixtures'
import { claim, member } from './__tests__/s3eFixtures'
import { releaseChanges } from './releaseChanges'

it('takes names and each side’s titles from its own release, including deleted fields', () => {
  const base = structuredClone(baseRelease()), current = structuredClone(currentRelease())
  current.members.find(item => item.logical_slug === 'entity/M1')!.payload.names = ['新名称']
  const profile = current.members.find(item => item.logical_slug === 'presentation/profile_medical')!
  const fields = (profile.payload.sections as { fields: { short_title: string }[] }[])[0]!.fields
  fields[2]!.short_title = '新标题'
  const changes = releaseChanges(current, base)!
  expect(changes.changed[0]).toMatchObject({ name: '新名称', fieldTitle: '新标题', before: { title: '等待期' }, after: { title: '新标题' } })
  expect(changes.removed[0]).toMatchObject({ name: '甲医疗', fieldTitle: '宽限期' })
})

it('retains multiple Claims and unknown fields in member order while sorting known fields by profile', () => {
  const base = structuredClone(baseRelease()), current = structuredClone(base)
  const extra = [claim('M1', 'z_extra', 'present', '甲'), claim('M1', 'a_extra', 'present', '乙'),
    { ...claim('M1', 'waiting_period', 'present', '60日'), logical_slug: 'M1/waiting_period/variant' }]
  current.members.push(...extra)
  expect(releaseChanges(current, base)!.added.map(row => row.slug)).toEqual([extra[2]!.logical_slug, extra[0]!.logical_slug, extra[1]!.logical_slug])
})

it('uses digest changes even with equal values, and preserves unknown/absent states and generated origin', () => {
  const base = structuredClone(baseRelease()), current = structuredClone(base)
  const changed = current.members.find(item => item.logical_slug === 'M1/waiting_period')!
  changed.member_digest = 'new'; changed.payload.origin = 'MODEL_GENERATED'
  const absent = current.members.find(item => item.logical_slug === 'M2/waiting_period')!
  absent.member_digest = 'absent'; absent.payload.state = 'absent_explicitly'
  const result = releaseChanges(current, base)!
  expect(result.changed[0]).toMatchObject({ before: { value: '90日。' }, after: { value: '90日。', origin: 'MODEL_GENERATED' } })
  expect(result.changed[1]).toMatchObject({ before: { state: 'unknown', value: null }, after: { state: 'absent_explicitly', value: null } })
})

it('counts non-Claim additions/deletions/digest changes without generating field rows or mutating inputs', () => {
  const base = structuredClone(baseRelease()), current = structuredClone(base)
  current.members = current.members.filter(item => item.kind !== 'concept')
  current.members.find(item => item.kind === 'navigation')!.member_digest = 'updated'
  current.members.push(member('concept', 'concept/new', { definition: '新增定义' }))
  const before = JSON.stringify([base, current])
  expect(releaseChanges(current, base)).toEqual({ added: [], changed: [], removed: [], otherChanged: 3 })
  expect(JSON.stringify([base, current])).toBe(before)
})

it('orders deletions by the base navigation even if the current navigation is rearranged', () => {
  const base = structuredClone(baseRelease()), current = structuredClone(base)
  current.members = current.members.filter(item => !['M1/waiting_period', 'C1/cooling_off_period'].includes(item.logical_slug))
  const navigation = current.members.find(item => item.kind === 'navigation')!
  const domains = navigation.payload.domains as { groups: unknown[] }[]
  domains[0]!.groups.reverse()
  expect(releaseChanges(current, base)!.removed.map(row => row.entityId)).toEqual(['M1', 'C1'])
})
