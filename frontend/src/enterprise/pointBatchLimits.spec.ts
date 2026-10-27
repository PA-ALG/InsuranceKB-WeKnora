// @vitest-environment happy-dom
// Claude clarified the >500 and blocked-unknown boundary in Issue #370, comment 6440079374.
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))
import { get, post } from '@/utils/request'
import { point, pointDetail, pointItem, pointResult } from './__tests__/reviewPointFixtures'
import { claim, member, release } from './__tests__/s3eFixtures'
import { ok, page, pointCard, views } from './__tests__/pointLifecycleHarness'

// Each case renders 500+ point cards in happy-dom (about 3 s alone); a loaded full run
// must not trip vitest's 5 s default.
const LARGE_RENDER_TIMEOUT = 30_000

afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })
async function batch(count: number, unknown: boolean, blocked = 0) {
  const slugs = Array.from({ length: count }, (_, i) => `new/field-${i}`)
  const detail = pointDetail('cand-1', slugs.map((slug, i) => point(slug, {
    kind: unknown ? 'claim' : 'member', blocker: i < blocked ? 'NEEDS_REBASE' : '',
  })), {
    bundle_removals: [], bundle_members: slugs.map((slug, i) => unknown
      ? { ...claim('new', `field-${i}`, 'unknown', null, 0), logical_slug: slug }
      : member('entity', slug, { entity_id: `new-${i}`, names: [`新产品${i}`] })),
  })
  vi.mocked(get).mockImplementation(async (url: string) => url.includes('/releases/') ? ok(release())
    : url.includes('?status=') ? ok({ items: [pointItem('cand-1', { point_count: count, pending_points: count })] }) : ok(detail))
  const view = page(); await flushPromises()
  return { view, slugs }
}

it.each([500, 501])('displays every one of %s points and never silently truncates approve-rest', async count => {
  const { view, slugs } = await batch(count, false)
  expect(view.findAll('[data-point]')).toHaveLength(count)
  const rest = view.get('[data-review-approve-rest]')
  expect(rest.text()).toContain(String(count))
  if (count > 500) {
    expect(rest.attributes('disabled')).toBeDefined()
    expect(view.text()).toContain('每次最多处理 500 项，请逐项处理至 500 项以内')
    expect(pointCard(view, slugs[0]).get('[data-point-approve]').attributes('disabled')).toBeUndefined()
    await rest.trigger('click'); expect(vi.mocked(post)).not.toHaveBeenCalled()
  } else {
    vi.mocked(post).mockResolvedValue(ok(pointResult(slugs, 'released', { status: 'released' })))
    await rest.trigger('click'); expect(vi.mocked(post)).not.toHaveBeenCalled()
    await rest.trigger('click'); await flushPromises()
    expect(vi.mocked(post)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(post).mock.calls[0][1]).toEqual({ slugs, outcome: 'approve', reason: '核对无误' })
    expect(view.text()).toContain('本产品已全部处理')
  }
}, LARGE_RENDER_TIMEOUT)

it('disables both unknown batch actions above 500, then enables them after one single decision', async () => {
  const { view, slugs } = await batch(501, true)
  expect(view.findAll('[data-point]')).toHaveLength(501)
  expect(view.get('[data-unknown-approve]').attributes('disabled')).toBeDefined()
  expect(view.get('[data-unknown-reject]').attributes('disabled')).toBeDefined()
  expect(view.get('[data-point-unknown-group]').text()).toContain('每次最多处理 500 项')
  vi.mocked(post).mockResolvedValueOnce(ok(pointResult([slugs[0]], 'released')))
  await pointCard(view, slugs[0]).get('[data-point-approve]').trigger('click'); await flushPromises()
  expect(view.get('[data-unknown-approve]').attributes('disabled')).toBeUndefined()
  expect(view.get('[data-unknown-reject]').attributes('disabled')).toBeUndefined()
  vi.mocked(post).mockResolvedValueOnce(ok(pointResult(slugs.slice(1), 'released', { status: 'released' })))
  await view.get('[data-unknown-approve]').trigger('click'); await flushPromises()
  expect(vi.mocked(post)).toHaveBeenCalledTimes(2)
  expect(vi.mocked(post).mock.calls[1][1]).toEqual({ slugs: slugs.slice(1), outcome: 'approve', reason: '核对无误' })
}, LARGE_RENDER_TIMEOUT)

it('applies the limit to each action after excluding blockers only for approval', async () => {
  const { view, slugs } = await batch(501, true, 1)
  expect(view.get('[data-unknown-approve]').attributes('disabled')).toBeUndefined()
  expect(view.get('[data-unknown-reject]').attributes('disabled')).toBeDefined()
  expect(view.get('[data-point-unknown-group]').text()).toContain('另有 1 项需先处理冲突')
  expect(view.get('[data-review-approve-rest]').attributes('disabled')).toBeUndefined()
  vi.mocked(post).mockResolvedValueOnce(ok(pointResult(slugs.slice(1), 'released')))
  await view.get('[data-unknown-approve]').trigger('click'); await flushPromises()
  expect(vi.mocked(post).mock.calls[0][1]).toEqual({ slugs: slugs.slice(1), outcome: 'approve', reason: '核对无误' })
  expect(view.get('[data-unknown-approve]').attributes('disabled')).toBeDefined()
  expect(view.get('[data-unknown-reject]').attributes('disabled')).toBeUndefined()
  vi.mocked(post).mockResolvedValueOnce(ok(pointResult([slugs[0]], 'rejected', { status: 'released' })))
  await view.get('[data-unknown-reject]').trigger('click')
  await view.get('[data-point-unknown-group] textarea').setValue('冲突字段不采用')
  await view.get('[data-point-unknown-group] [data-point-confirm-reject]').trigger('click'); await flushPromises()
  expect(vi.mocked(post).mock.calls[1][1]).toEqual({ slugs: [slugs[0]], outcome: 'reject', reason: '冲突字段不采用' })
}, LARGE_RENDER_TIMEOUT)
