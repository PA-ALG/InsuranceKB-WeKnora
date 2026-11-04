import { describe, expect, it } from 'vitest'
import type { Release, ReleaseMember, ReviewDetail, ReviewPoint } from './enterpriseApi'
import { reviewRows, type ReviewRow } from './reviewView'
import { pointItem } from './__tests__/reviewPointFixtures'

type Payload = Record<string, unknown>
interface Cell { present: boolean; value?: unknown; explanation?: string }
interface EntityChange { beforeKnown: boolean; fields: { path: string; before: Cell; after: Cell }[] }
const entity = (payload: Payload, kind = 'entity'): ReleaseMember => ({
  kind, logical_slug: 'entity/E1', payload, member_digest: 'a'.repeat(64), access_scope: 'space',
})
const payload = (extra: Payload = {}): Payload => ({ entity_id: 'E1', entity_type: 'product', names: ['合成产品'], ...extra })
const base = (value: Payload): Release => ({ id: 'r1', epoch: 1, members: [entity(value)] })
function detail(value: Payload | null, extra: Partial<ReviewDetail> = {}): ReviewDetail {
  const point: ReviewPoint = { slug: 'entity/E1', kind: value ? 'member' : 'removal', status: 'pending',
    decision: null, release_id: null, blocker: '' }
  return { ...pointItem('c1', { subjects: ['E1'], point_count: 1, pending_points: 1 }),
    head_release_id: 'r1', blocker: '', bundle_members: value ? [entity(value)] : [],
    bundle_removals: value ? [] : ['entity/E1'], points: [point], ...extra }
}
function projected(next: Payload | null, release: Release | null, extra: Partial<ReviewDetail> = {}) {
  return reviewRows(detail(next, extra), release).get('entity/E1') as ReviewRow & { entity: EntityChange }
}

describe('entity review projection from the paired snapshot', () => {
  it('uses the candidate name without claims or a presentation profile, retaining slug identity', () => {
    const row = projected(payload({ names: ['  ', '合成新名称'] }), base(payload()))
    expect(row.title).toBe('合成新名称')
    expect(row.slug).toBe('entity/E1')
    expect(row.entity).toBeDefined()
    expect(projected(payload({ names: [] }), base(payload())).title).toBe('E1')
    expect(projected({ entity_type: 'product' }, null, { head_release_id: null }).title).toBe('entity/E1')
  })

  it('lists exact nested lifecycle, family and identifier changes without unchanged data', () => {
    const row = projected(payload({ lifecycle: { sale_start: '2025-02-01', sale_end: null },
      product_family: { key: 'f', display_name: '合成系列乙' }, identifiers: { external: 'new' } }),
    base(payload({ lifecycle: { sale_start: '2025-01-01', sale_end: null },
      product_family: { key: 'f', display_name: '合成系列甲' }, identifiers: { external: 'old' } })))
    expect(row.entity.fields.map(field => field.path)).toEqual([
      '/identifiers/external', '/lifecycle/sale_start', '/product_family/display_name',
    ])
    expect(row.entity.fields[1]).toMatchObject({ before: { present: true, value: '2025-01-01' },
      after: { present: true, value: '2025-02-01' } })
  })

  it('distinguishes absent keys, null, empty string, false and zero, and preserves unknown paths', () => {
    const row = projected(payload({ future: { fresh: null, empty: '', bool: false, zero: 0 },
      'odd/key': { 'a~b': 'new' } }), base(payload({ future: { empty: null, bool: '', zero: false },
      'odd/key': { 'a~b': 'old' } })))
    const fields = row.entity.fields
    expect(fields.find(field => field.path === '/future/fresh')).toMatchObject({
      before: { present: false }, after: { present: true, value: null },
    })
    expect(fields.find(field => field.path === '/future/empty')?.after.value).toBe('')
    expect(fields.find(field => field.path === '/future/bool')?.after.value).toBe(false)
    expect(fields.find(field => field.path === '/future/zero')?.after.value).toBe(0)
    expect(fields.find(field => field.path === '/odd~1key/a~0b')?.before.value).toBe('old')
    const removed = projected(payload(), base(payload({ extra: 'removed' })))
    expect(removed.entity.fields).toEqual([{ path: '/extra', before: { present: true, value: 'removed' }, after: { present: false } }])
  })

  it('ignores object key order but treats ordered arrays and empty containers as full values', () => {
    expect(projected(payload({ extra: { a: 1, b: 2 } }), base(payload({ extra: { b: 2, a: 1 } }))).entity.fields).toEqual([])
    const row = projected(payload({ aliases: ['B', 'A'], extra: {}, list: [], type: { a: 'x' } }),
      base(payload({ aliases: ['A', 'B'], extra: { a: 1 }, list: ['x'], type: 'old' })))
    expect(row.entity.fields.map(field => field.path)).toEqual(['/aliases', '/extra/a', '/list', '/type'])
    expect(row.entity.fields.find(field => field.path === '/type')?.after.value).toEqual({ a: 'x' })
    expect(row.entity.fields.find(field => field.path === '/extra/a')?.after.present).toBe(false)
  })

  it('expands new/deleted objects, preserves empty ones, and names a removed entity from its snapshot', () => {
    const added = projected(payload({ extra: { nested: 'new' }, empty: {} }), null, { head_release_id: null })
    expect(added.entity.beforeKnown).toBe(true)
    expect(added.entity.fields.find(field => field.path === '/extra/nested')?.before.present).toBe(false)
    expect(added.entity.fields.find(field => field.path === '/empty')?.after.value).toEqual({})
    const removed = projected(null, base(payload({ extra: { nested: 'old' } })))
    expect(removed.title).toBe('合成产品')
    expect(removed.entity.fields.every(field => !field.after.present)).toBe(true)
  })

  it('does not borrow before values or profiles from an unavailable or different Release', () => {
    for (const release of [null, { ...base(payload({ extra: 'unrelated old value' })), id: 'other' }]) {
      const row = projected(payload({ extra: 'candidate' }), release)
      expect(row.entity.beforeKnown).toBe(false)
      expect(row.entity.fields.every(field => !field.before.present)).toBe(true)
      expect(JSON.stringify(row)).not.toContain('unrelated old value')
    }
  })

  it('explains each notice token from its own matched profile and retains unknown tokens', () => {
    const profile = (notices: Payload): ReleaseMember => ({ ...entity({ entity_types: ['product'], notices }),
      kind: 'presentation_profile', logical_slug: 'presentation/demo' })
    const release = base(payload({ identifiers: { notice: 'old' } }))
    release.members.push(profile({ old: '旧版说明', next: '不该借用的旧解释' }))
    const d = detail(payload({ identifiers: { notice: 'next' } }))
    d.bundle_members.push(profile({ next: '候选说明' }))
    const row = reviewRows(d, release).get('entity/E1') as ReviewRow & { entity: EntityChange }
    expect(row.entity.fields).toEqual([{ path: '/identifiers/notice',
      before: { present: true, value: 'old', explanation: '旧版说明' },
      after: { present: true, value: 'next', explanation: '候选说明' } }])
    const unknown = projected(payload({ identifiers: { notice: 'future' } }), base(payload()))
    expect(unknown.entity.fields.find(field => field.path === '/identifiers/notice')?.after).toEqual({ present: true, value: 'future' })
    const same = detail(payload({ identifiers: { notice: 'old' } }))
    same.bundle_members.push(profile({ old: '仅字典变化' }))
    const unchanged = reviewRows(same, release).get('entity/E1') as ReviewRow & { entity: EntityChange }
    expect(unchanged.entity.fields).toEqual([])
    const deleted = projected(payload({ identifiers: {} }), release)
    expect(deleted.entity.fields).toEqual([{ path: '/identifiers/notice',
      before: { present: true, value: 'old', explanation: '旧版说明' }, after: { present: false } }])
  })

  it('does not treat a nonentity member as an entity merely because of its slug', () => {
    const d = detail(payload())
    d.bundle_members[0] = entity({ names: ['not an entity'] }, 'navigation')
    const row = reviewRows(d, null).get('entity/E1') as ReviewRow & { entity?: EntityChange }
    expect(row.entity).toBeUndefined()
    expect(row.title).toBe('entity/E1')
  })
})
