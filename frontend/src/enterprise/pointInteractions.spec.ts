// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))
import { get, post } from '@/utils/request'
import { point, pointDetail, pointItem, pointResult, UNKNOWN_SLUGS } from './__tests__/reviewPointFixtures'
import { claim, member, release } from './__tests__/s3eFixtures'
import { deferred, draft, ok, page, pointCard, transport, views } from './__tests__/pointLifecycleHarness'

afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

it('sorts products by submission time and reads other products only when opened', async () => {
  vi.mocked(get).mockImplementation(async (url: string) => url.includes('/releases/') ? ok(release())
    : url.includes('?status=') ? ok({ items: [pointItem('later'), pointItem('first', { created_at: '2026-10-26T00:00:00Z' })] })
      : ok(pointDetail(url.endsWith('/first') ? 'first' : 'later')))
  const view = page(); await flushPromises()
  expect(view.findAll('[data-review-item]').map(item => item.attributes('data-review-item'))).toEqual(['first', 'later'])
  expect(vi.mocked(get).mock.calls.filter(([url]) => url.endsWith('/later'))).toHaveLength(0)
  await view.get('[data-review-item="later"] [data-review-open]').trigger('click'); await flushPromises()
  expect(view.get('[data-review-item="later"] [data-review-open]').attributes('aria-expanded')).toBe('true')
  await view.get('[data-review-item="later"] [data-review-open]').trigger('click')
  await view.get('[data-review-item="later"] [data-review-open]').trigger('click')
  expect(vi.mocked(get).mock.calls.filter(([url]) => url.endsWith('/later'))).toHaveLength(1)
})

it('handles an unknown field on its own and focuses its visible result', async () => {
  transport(); vi.mocked(post).mockResolvedValue(ok(pointResult([UNKNOWN_SLUGS[0]], 'released')))
  const view = page(); await flushPromises()
  const card = pointCard(view, UNKNOWN_SLUGS[0])
  ;(card.element.closest('details') as HTMLDetailsElement).open = true
  await card.get('[data-point-approve]').trigger('click'); await flushPromises()
  expect(vi.mocked(post).mock.calls[0][1]).toEqual({ slugs: [UNKNOWN_SLUGS[0]], outcome: 'approve', reason: '核对无误' })
  expect(document.activeElement).toBe(card.get('[data-point-state]').element)
  expect((card.element.closest('details') as HTMLDetailsElement).open).toBe(true)
  expect(view.get('[data-review-progress]').text()).toContain('待审 6')
})

it('rejects every pending unknown with one trimmed reason and one request', async () => {
  transport(); vi.mocked(post).mockResolvedValue(ok(pointResult(UNKNOWN_SLUGS, 'rejected')))
  const view = page(); await flushPromises()
  const group = view.get('[data-point-unknown-group]')
  await group.get('[data-unknown-reject]').trigger('click')
  await group.get('textarea').setValue('\u0085 未在材料中找到 \u0085')
  await group.get('[data-point-confirm-reject]').trigger('click'); await flushPromises()
  expect(vi.mocked(post)).toHaveBeenCalledTimes(1)
  expect(vi.mocked(post).mock.calls[0][1]).toEqual({ slugs: UNKNOWN_SLUGS, outcome: 'reject', reason: '未在材料中找到' })
  expect(group.find('[data-unknown-approve]').exists()).toBe(false)
  expect(group.findAll('[data-point-state]')).toHaveLength(2)
  expect(document.activeElement).toBe(group.get('[data-point-state]').element)
})

it('keeps a blocked unknown visible and excludes it from group approval', async () => {
  transport(); const normal = vi.mocked(get).getMockImplementation()!
  const detail = pointDetail(); detail.points[0].blocker = 'NEEDS_REBASE'
  vi.mocked(get).mockImplementation(async (url: string) => url.endsWith('/candidates/cand-1') ? ok(detail) : normal(url))
  const view = page(); await flushPromises()
  expect(view.get('[data-unknown-approve]').attributes('disabled')).toBeUndefined()
  expect(view.get('[data-unknown-reject]').attributes('disabled')).toBeUndefined()
  expect(view.get('[data-point-unknown-group]').text()).toContain('另有 1 项需先处理冲突')
  vi.mocked(post).mockResolvedValue(ok(pointResult([UNKNOWN_SLUGS[1]], 'released')))
  await view.get('[data-unknown-approve]').trigger('click'); await flushPromises()
  expect(vi.mocked(post).mock.calls[0][1]).toEqual({ slugs: [UNKNOWN_SLUGS[1]], outcome: 'approve', reason: '核对无误' })
  expect(pointCard(view, UNKNOWN_SLUGS[0]).get('[data-point-blocker]').text()).toContain('当前版本已改过这一项')
})

it('requires fresh rest confirmation after a point decision changes its target set', async () => {
  transport(); vi.mocked(post).mockResolvedValue(ok(pointResult(['M1/waiting_period'], 'released')))
  const view = page(); await flushPromises()
  await view.get('[data-review-approve-rest]').trigger('click')
  expect(view.get('[data-review-approve-rest]').text()).toContain('确认批准')
  await pointCard(view).get('[data-point-approve]').trigger('click'); await flushPromises()
  expect(view.get('[data-review-approve-rest]').text()).toBe('批准其余 5 项')
  await view.get('[data-review-approve-rest]').trigger('click')
  expect(vi.mocked(post)).toHaveBeenCalledTimes(1)
})

it('uses the default for a whitespace approval reason but does not truncate an overlong reason', async () => {
  transport(); vi.mocked(post).mockResolvedValue(ok(pointResult(['M1/waiting_period'], 'released')))
  const view = page(); await flushPromises()
  const input = await draft(view)
  await input.setValue('😀'.repeat(2001))
  expect(pointCard(view).get('[data-point-approve]').attributes('disabled')).toBeDefined()
  await input.setValue('\u0085\u2003 ')
  await pointCard(view).get('[data-point-approve]').trigger('click'); await flushPromises()
  expect(vi.mocked(post).mock.calls[0][1]).toEqual({ slugs: ['M1/waiting_period'], outcome: 'approve', reason: '核对无误' })
})

it('keeps a failed batch retryable without rereading the list or losing its reason', async () => {
  transport(); vi.mocked(post).mockRejectedValueOnce({ status: 503, code: 'SERVICE_UNAVAILABLE' })
  const view = page(); await flushPromises()
  const group = view.get('[data-point-unknown-group]')
  await group.get('[data-unknown-reject]').trigger('click'); await group.get('textarea').setValue('待补材料')
  await group.get('[data-point-confirm-reject]').trigger('click'); await flushPromises()
  expect(group.text()).toContain('SERVICE_UNAVAILABLE')
  expect((group.get('textarea').element as HTMLTextAreaElement).value).toBe('待补材料')
  vi.mocked(post).mockResolvedValueOnce(ok(pointResult(UNKNOWN_SLUGS, 'rejected')))
  await group.get('[data-point-confirm-reject]').trigger('click'); await flushPromises()
  expect(group.findAll('[data-point-state]')).toHaveLength(2)
  expect(vi.mocked(get).mock.calls.filter(([url]) => url.includes('?status='))).toHaveLength(1)
})

it('drops a late snapshot read after changing Space without moving focus', async () => {
  transport(); const normal = vi.mocked(get).getMockImplementation()!, pending = deferred()
  vi.mocked(get).mockImplementation(async (url: string) => url.endsWith('/releases/new-head') ? pending.promise
    : url.includes('/spaces/demo/') && url.endsWith('/candidates/cand-1')
      ? ok(pointDetail('cand-1', undefined, { head_release_id: 'new-head' })) : normal(url))
  const view = page(); await flushPromises()
  await view.setProps({ spaceId: 'other' }); await flushPromises()
  const input = await draft(view)
  pending.resolve(ok({ ...release(), id: 'new-head' })); await flushPromises()
  expect(document.activeElement).toBe(input.element)
  expect((input.element as HTMLTextAreaElement).value).toBe('新的审核草稿')
})

it('projects new products and several claims for the same field without a fixture-specific mapping', async () => {
  const details = pointDetail('cand-1', [point('new/one'), point('new/two')], {
    head_release_id: null, subjects: ['new-product'], bundle_removals: [],
    bundle_members: [
      member('entity', 'entity/new-product', { entity_id: 'new-product', names: ['新产品'], classification_labels: ['new-class'] }),
      member('presentation_profile', 'profile/new-class', { classification_labels: ['new-class'], sections: [
        { section_key: 'terms', display_name: '条款', fields: [{ field_key: 'custom-field', short_title: '自定义条款' }] },
      ] }),
      { ...claim('new-product', 'custom-field', 'present', '第一项', 0), logical_slug: 'new/one' },
      { ...claim('new-product', 'custom-field', 'present', '第二项', 0), logical_slug: 'new/two' },
    ],
  })
  vi.mocked(get).mockImplementation(async (url: string) => url.includes('/releases/')
    ? Promise.reject({ code: 'RELEASE_NOT_FOUND', status: 404 })
    : url.includes('?status=') ? ok({ items: [pointItem()] }) : ok(details))
  const view = page(); await flushPromises()
  expect(view.findAll('[data-point]')).toHaveLength(2)
  expect(pointCard(view, 'new/one').text()).toContain('新产品 · 自定义条款')
  expect(pointCard(view, 'new/two').get('[data-point-after]').text()).toContain('第二项')
  expect(pointCard(view, 'new/one').get('[data-point-approve]').attributes('disabled')).toBeUndefined()
})

it('identifies an existing non-claim removal without showing its raw payload', async () => {
  const detail = pointDetail('cand-1', [point('entity/M1', { kind: 'removal' })], {
    bundle_members: [], bundle_removals: ['entity/M1'],
  })
  vi.mocked(get).mockImplementation(async (url: string) => url.includes('/releases/') ? ok(release())
    : url.includes('?status=') ? ok({ items: [pointItem()] }) : ok(detail))
  const view = page(); await flushPromises()
  const before = pointCard(view, 'entity/M1').get('[data-point-before]')
  expect(before.text()).toContain('现有内容')
  expect(before.text()).not.toContain('此前没有此项')
  expect(pointCard(view, 'entity/M1').text()).not.toContain('classification_labels')
  expect(pointCard(view, 'entity/M1').find('[data-point-after]').exists()).toBe(false)
})

it('does not claim a zero-point pending candidate has been processed', async () => {
  vi.mocked(get).mockImplementation(async (url: string) => url.includes('/releases/') ? ok(release())
    : url.includes('?status=') ? ok({ items: [pointItem('cand-1', { point_count: 0, pending_points: 0 })] })
      : ok(pointDetail('cand-1', [])))
  const view = page(); await flushPromises()
  expect(view.text()).toContain('没有可展示的字段变化')
  expect(view.text()).not.toContain('本产品已全部处理')
  expect(view.find('[data-review-approve-rest]').exists()).toBe(false)
})
