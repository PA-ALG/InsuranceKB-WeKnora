// S3h-2 acceptance (protected, written by Claude): what changed in a release relative to its base
// (Spec docs/design/slices/S3h-全文搜索与本版变化.md §3.1). Synthetic data only.
import { describe, expect, it } from 'vitest'
import { baseRelease, currentRelease, navigationOnlyRelease } from './__tests__/changesFixtures'
import { releaseChanges } from './releaseChanges'

const brief = (rows: { slug: string; entityId: string; name: string; fieldKey: string; fieldTitle: string }[]) =>
  rows.map(row => [row.slug, row.entityId, row.name, row.fieldKey, row.fieldTitle])

describe('release changes', () => {
  it('lists added, changed and removed claims in product and field order', () => {
    const changes = releaseChanges(currentRelease(), baseRelease())!
    expect(brief(changes.added)).toEqual([['C1/waiting_period', 'C1', '丙重疾', 'waiting_period', '等待期']])
    expect(brief(changes.changed)).toEqual([
      ['M1/waiting_period', 'M1', '甲医疗', 'waiting_period', '等待期'],
      ['C1/cooling_off_period', 'C1', '丙重疾', 'cooling_off_period', '犹豫期'],
    ])
    expect(brief(changes.removed)).toEqual([['M1/premium_grace_period', 'M1', '甲医疗', 'premium_grace_period', '宽限期']])
  })

  it('carries the field on each side, empty where it does not exist', () => {
    const changes = releaseChanges(currentRelease(), baseRelease())!
    const [changed] = changes.changed
    expect(changed!.before!.value).toBe('90日。')
    expect(changed!.after!.value).toBe('180日。')
    expect(changes.added[0]!.before).toBeNull()
    expect(changes.added[0]!.after!.value).toBe('180日。')
    expect(changes.removed[0]!.before!.value).toBe('60日。')
    expect(changes.removed[0]!.after).toBeNull()
  })

  it('only counts members that are not claims', () => {
    expect(releaseChanges(currentRelease(), baseRelease())!.otherChanged).toBe(1)
    const changes = releaseChanges(navigationOnlyRelease(), baseRelease())!
    expect([changes.added, changes.changed, changes.removed]).toEqual([[], [], []])
    expect(changes.otherChanged).toBe(1)
  })

  it('has nothing to compare without a base', () => {
    expect(releaseChanges(currentRelease(), null)).toBeNull()
  })
})
