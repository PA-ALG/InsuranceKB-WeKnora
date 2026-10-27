// @vitest-environment happy-dom
// Implementation-owned: real page + state + API; only transport is replaced.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))
import { get, post } from '@/utils/request'
import { decidePoints, EnterpriseError } from './enterpriseApi'
import { pointDetail, pointItem, pointResult } from './__tests__/reviewPointFixtures'
import { release } from './__tests__/s3eFixtures'
import { deferred, draft, ok, page, pointCard, transport, views } from './__tests__/pointLifecycleHarness'

afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

describe('point decision lifecycle over HTTP', () => {
  it.each([401, 403])('keeps a %s decision refusal local and lets the same point recover', async status => {
    transport()
    const refusal = { success: false, code: 'RELEASE_ACCESS_DENIED', $httpStatus: status }
    vi.mocked(post).mockResolvedValueOnce(refusal)
    const view = page(); await flushPromises()
    await pointCard(view).get('[data-point-approve]').trigger('click'); await flushPromises()
    expect(pointCard(view).get('[role="alert"]').text()).toContain('RELEASE_ACCESS_DENIED')
    expect(pointCard(view).find('[data-point-state]').exists()).toBe(false)
    expect(pointCard(view).get('[data-point-approve]').attributes('disabled')).toBeUndefined()
    vi.mocked(post).mockResolvedValueOnce(ok(pointResult(['M1/waiting_period'], 'released')))
    await pointCard(view).get('[data-point-approve]').trigger('click'); await flushPromises()
    expect(document.activeElement).toBe(pointCard(view).get('[data-point-state]').element)
    expect(vi.mocked(get).mock.calls.filter(([url]) => url.includes('?status='))).toHaveLength(1)
  })

  it('preserves the typed refusal envelope at the point API boundary', async () => {
    const refusal = { success: false, code: 'RELEASE_ACCESS_DENIED', $httpStatus: 403 }
    vi.mocked(post).mockResolvedValue(refusal)
    const result = decidePoints('space', 'candidate', ['field'], 'approve', 'reason')
    await expect(result).rejects.toBeInstanceOf(EnterpriseError)
    await expect(result).rejects.toMatchObject({ code: 'RELEASE_ACCESS_DENIED', status: 403 })
  })

  it.each(['success', 'MEMBER_DECIDED', 'NEEDS_REBASE', 'CANDIDATE_DECIDED', 'SERVICE_UNAVAILABLE'].flatMap(outcome =>
    ['space', 'tab', 'unmount'].map(change => ({ outcome, change }))))('ignores late $outcome after $change', async ({ outcome, change }) => {
    transport(); const pending = deferred(); vi.mocked(post).mockReturnValue(pending.promise)
    const view = page(); await flushPromises()
    await pointCard(view).get('[data-point-approve]').trigger('click')
    if (change === 'space') await view.setProps({ spaceId: 'other' })
    else if (change === 'tab') {
      await view.get('[data-review-tab="decided"]').trigger('click'); await flushPromises()
      await view.get('[data-review-tab="pending"]').trigger('click')
    } else { view.unmount(); views.splice(views.indexOf(view), 1) }
    await flushPromises()
    const input = change === 'unmount' ? null : await draft(view)
    const reads = vi.mocked(get).mock.calls.length
    const focused = document.activeElement
    if (outcome === 'success') pending.resolve(ok(pointResult(['M1/waiting_period'], 'released')))
    else pending.reject({ status: 409, code: outcome })
    await flushPromises()
    expect(vi.mocked(get).mock.calls.length).toBe(reads)
    expect(document.activeElement).toBe(focused)
    if (input) {
      expect((input.element as HTMLTextAreaElement).value).toBe('新的审核草稿')
      expect(view.find('[data-point-state]').exists()).toBe(false)
      expect(view.find('[data-review-notice]').exists()).toBe(false)
    }
  })

  it.each(['MEMBER_DECIDED', 'NEEDS_REBASE', 'CANDIDATE_DECIDED'].flatMap(code =>
    ['returns', 'fails'].map(outcome => ({ code, outcome }))))('ignores a stale $code refresh that $outcome', async ({ code, outcome }) => {
    transport(); const view = page(); await flushPromises()
    const pending = deferred(); const normal = vi.mocked(get).getMockImplementation()!
    vi.mocked(get).mockImplementationOnce(() => pending.promise).mockImplementation(normal)
    vi.mocked(post).mockRejectedValue({ status: 409, code })
    await pointCard(view).get('[data-point-approve]').trigger('click'); await flushPromises()
    await view.setProps({ spaceId: 'other' }); await flushPromises()
    const input = await draft(view)
    if (outcome === 'fails') pending.reject({ status: 503, code: 'SERVICE_UNAVAILABLE' })
    else pending.resolve(code === 'CANDIDATE_DECIDED' ? ok({ items: [] }) : ok(pointDetail()))
    await flushPromises()
    expect(document.activeElement).toBe(input.element)
    expect((input.element as HTMLTextAreaElement).value).toBe('新的审核草稿')
    expect(view.find('[data-review-notice]').exists()).toBe(false)
  })

  it('refreshes the list only when the whole candidate has been decided', async () => {
    transport(); const view = page(); await flushPromises()
    vi.mocked(post).mockRejectedValue({ status: 409, code: 'CANDIDATE_DECIDED' })
    await pointCard(view).get('[data-point-approve]').trigger('click'); await flushPromises()
    expect(vi.mocked(get).mock.calls.filter(([url]) => url.endsWith('?status=pending'))).toHaveLength(2)
    expect(view.get('[data-review-notice]').text()).toContain('已由其他人处理')
    expect(document.activeElement).toBe(view.get('[data-review-tab="pending"]').element)
  })

  it('serializes overlapping decisions within a product, including batch actions', async () => {
    transport(); const pending = deferred(); vi.mocked(post).mockReturnValue(pending.promise)
    const view = page(); await flushPromises()
    const approve = pointCard(view).get('[data-point-approve]')
    await approve.trigger('click'); await approve.trigger('click')
    expect(pointCard(view, 'M2/waiting_period').get('[data-point-reject]').attributes('disabled')).toBeDefined()
    expect(view.get('[data-review-approve-rest]').attributes('disabled')).toBeDefined()
    expect(view.get('[data-unknown-approve]').attributes('disabled')).toBeDefined()
    expect(vi.mocked(post)).toHaveBeenCalledTimes(1)
    pending.resolve(ok(pointResult(['M1/waiting_period'], 'released'))); await flushPromises()
    expect(pointCard(view, 'M2/waiting_period').get('[data-point-approve]').attributes('disabled')).toBeUndefined()
  })

  it('counts Go whitespace and Unicode code points in both reason modes', async () => {
    transport(); vi.mocked(post).mockResolvedValue(ok(pointResult(['M1/waiting_period'], 'rejected')))
    const view = page(); await flushPromises()
    await pointCard(view).get('[data-point-reject]').trigger('click')
    const input = pointCard(view).get('textarea')
    await input.setValue('\u0085\u2003 ')
    expect(pointCard(view).get('[data-point-confirm-reject]').attributes('disabled')).toBeDefined()
    await input.setValue('\uFEFF' + 'a'.repeat(2000))
    expect(pointCard(view).get('[data-point-confirm-reject]').attributes('disabled')).toBeDefined()
    await input.setValue('\u0085' + '😀'.repeat(2000) + '\u0085')
    expect(pointCard(view).get('[data-point-confirm-reject]').attributes('disabled')).toBeUndefined()
    await pointCard(view).get('[data-point-confirm-reject]').trigger('click'); await flushPromises()
    expect(vi.mocked(post).mock.calls[0][1]).toEqual({ slugs: ['M1/waiting_period'], outcome: 'reject', reason: '😀'.repeat(2000) })
    expect(view.findAll('[data-point-quote] a, .ek-source')).toHaveLength(0)
  })

  it('keeps denied details empty and retries through the protected detail route', async () => {
    transport(); const normal = vi.mocked(get).getMockImplementation()!
    let denied = true
    vi.mocked(get).mockImplementation(async (url: string) => url.endsWith('/candidates/cand-1') && denied
      ? Promise.reject({ status: 403, code: 'RELEASE_ACCESS_DENIED' }) : normal(url))
    const view = page(); await flushPromises()
    expect(view.find('[data-point]').exists()).toBe(false)
    expect(view.get('[role="alert"]').text()).toContain('RELEASE_ACCESS_DENIED')
    denied = false
    await view.findAll('button').find(button => button.text() === '重试')!.trigger('click'); await flushPromises()
    expect(pointCard(view).find('[data-point-quote]').exists()).toBe(true)
  })

  it.each([
    { status: 'pending', release_id: 'r', epoch: 1, points: [] },
    pointResult(['different-slug'], 'released'),
    pointResult(['M1/waiting_period', 'M1/waiting_period'], 'released'),
    pointResult(['M1/waiting_period'], 'released', { epoch: null }),
    pointResult(['M1/waiting_period'], 'rejected'),
  ])('does not apply malformed or mismatched successful batches: %j', async result => {
    transport(); vi.mocked(post).mockResolvedValue(ok(result))
    const view = page(); await flushPromises()
    await pointCard(view).get('[data-point-approve]').trigger('click'); await flushPromises()
    expect(pointCard(view).get('[role="alert"]').text()).toContain('INVALID_RESPONSE')
    expect(view.find('[data-point-state]').exists()).toBe(false)
    expect(view.get('[data-review-progress]').text()).toContain('待审 7')
  })

  it('does not compare a detail to the wrong release and retries the section snapshot', async () => {
    transport(); const normal = vi.mocked(get).getMockImplementation()!
    vi.mocked(get).mockImplementation(async (url: string) => {
      if (url.endsWith('/candidates/cand-1')) return ok(pointDetail('cand-1', undefined, { head_release_id: 'new-head' }))
      if (url.endsWith('/releases/new-head')) throw { status: 403, code: 'RELEASE_ACCESS_DENIED' }
      return normal(url)
    })
    const view = page(); await flushPromises()
    expect(pointCard(view).find('[data-point-before]').exists()).toBe(false)
    expect(pointCard(view).get('[data-point-approve]').attributes('disabled')).toBeDefined()
    expect(pointCard(view).get('[data-point-reject]').attributes('disabled')).toBeUndefined()
    vi.mocked(get).mockImplementation(async (url: string) => url.endsWith('/releases/new-head')
      ? ok({ ...release(), id: 'new-head' }) : url.endsWith('/candidates/cand-1')
        ? ok(pointDetail('cand-1', undefined, { head_release_id: 'new-head' })) : normal(url))
    await view.findAll('button').find(button => button.text() === '重试')!.trigger('click'); await flushPromises()
    expect(pointCard(view).get('[data-point-approve]').attributes('disabled')).toBeUndefined()
    expect(vi.mocked(get).mock.calls.filter(([url]) => url.includes('?status='))).toHaveLength(1)
  })

  it('rejects a detail for a different candidate without showing its payload', async () => {
    transport(); const normal = vi.mocked(get).getMockImplementation()!
    vi.mocked(get).mockImplementation(async (url: string) => url.endsWith('/candidates/cand-1') ? ok(pointDetail('other')) : normal(url))
    const view = page(); await flushPromises()
    expect(view.find('[data-point]').exists()).toBe(false)
    expect(view.get('[role="alert"]').text()).toContain('INVALID_RESPONSE')
  })
})
