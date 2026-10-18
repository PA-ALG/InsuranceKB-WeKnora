import { describe, expect, it } from 'vitest'
import { homeClaim, homeRelease } from './__tests__/spaceHomeFixtures'
import { overviewShortValue, spaceHomeView } from './spaceHomeView'

describe('overview short values', () => {
  it.each([
    ['1. 保障为20年；可续保', '20年'],
    ['金额为1.5万元，按约定支付', '1.5万元'],
    ['1.5万元，按约定支付', '1.5万元'],
    ['金额为1,000元，详见条款', '1,000元'],
    ['金额为10,000.50元，详见条款', '10,000.50元'],
    ['保障比例为-10%，详见条款', '-10%'],
    ['金额为1,00元，详见条款', '金额为1,00元'],
    ['出生满28日至70周岁。其他规则', '出生满28日至70周岁'],
    ['最高比例为80%，其余自付', '80%'],
    ['无数字的完整首句；后续说明', '无数字的完整首句'],
    ['甲'.repeat(25), '甲'.repeat(24) + '…'],
    ['𠮷'.repeat(25), '𠮷'.repeat(24) + '…'],
  ])('formats %s', (value, expected) => expect(overviewShortValue(value)).toBe(expected))
})

describe('home data from its release', () => {
  it('uses published order and titles, hides empty groups and counts the entire release', () => {
    const view = spaceHomeView(homeRelease())
    expect(view.title).toBe('示例知识库')
    expect(view.columns).toEqual([{ key: 'field_1', title: '字段 1' }, { key: 'field_0', title: '字段 0' }])
    expect(view.groups.map(group => group.key)).toEqual(['alpha', 'beta'])
    expect(view.productCount).toBe(3)
    expect(view.concepts).toHaveLength(12)
    expect(view.concepts.slice(0, 3).map(concept => concept.key)).toEqual(['field_2', 'field_0', 'field_1'])
  })

  it('counts distinct stated products, not claims or unknown states', () => {
    const release = homeRelease()
    release.members.push(homeClaim('A', 'field_0', '另一个范围', 'present', '/scope-2'))
    const concepts = spaceHomeView(release).concepts
    expect(concepts[0]).toMatchObject({ key: 'field_2', count: 3 })
    expect(concepts.find(concept => concept.key === 'field_0')?.count).toBe(2)
  })

  it('preserves every applicability value and model provenance in overview cells', () => {
    const release = homeRelease()
    const generated = homeClaim('A', 'field_1', '另一适用范围10日', 'present', '/scope-2')
    generated.payload.origin = 'MODEL_GENERATED'
    release.members.push(generated)
    const cell = spaceHomeView(release).groups[0]!.rows[0]!.cells[0]!
    expect(cell.values.map(value => value.text)).toEqual(['20日', '10日'])
    expect(cell.values.map(value => value.generated)).toEqual([false, true])
    expect(cell.fullValue).toBe('保障为20日，详见条款。\n另一适用范围10日')
  })

  it('keeps old releases navigable when navigation metadata is omitted', () => {
    const release = homeRelease()
    delete release.members[0]!.payload.display_name
    delete release.members[0]!.payload.overview_fields
    const old = spaceHomeView(release)
    expect(old.title).toBe('')
    expect(old.columns).toEqual([])
    expect(old.groups.flatMap(group => group.rows)).toHaveLength(3)
    release.members = release.members.filter(member => member.kind !== 'navigation')
    expect(spaceHomeView(release).groups.flatMap(group => group.rows)).toHaveLength(3)
  })
})
