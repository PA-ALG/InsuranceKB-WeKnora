// RV5b acceptance (protected, written by Claude): the RV5a session routes that list a Space's
// candidates, read one and record a person's decision (Spec docs/design/slices/RV5b-人工审核队列页面.md §2).
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))

import { get, post } from '@/utils/request'
import { decideReview, EnterpriseError, listReviews, readReview } from './enterpriseApi'
import { reviewDetail, reviewItem, reviewResult } from './__tests__/reviewFixtures'

afterEach(() => vi.resetAllMocks())
const ok = (data: unknown) => ({ success: true, data, $httpStatus: 200 })

describe('review session API', () => {
  it('encodes the Space, passes the status, and unwraps the items', async () => {
    vi.mocked(get).mockResolvedValue(ok({ items: [reviewItem()] }))
    await expect(listReviews('demo/space', 'pending')).resolves.toEqual([reviewItem()])
    await listReviews('demo/space', 'decided')
    expect(vi.mocked(get).mock.calls.map(call => call[0])).toEqual([
      '/api/v1/enterprise/spaces/demo%2Fspace/view/candidates?status=pending',
      '/api/v1/enterprise/spaces/demo%2Fspace/view/candidates?status=decided',
    ])
  })

  it('reads one candidate by its encoded id', async () => {
    vi.mocked(get).mockResolvedValue(ok(reviewDetail('cand/1')))
    await expect(readReview('demo', 'cand/1')).resolves.toEqual(reviewDetail('cand/1'))
    expect(vi.mocked(get).mock.calls[0][0]).toBe('/api/v1/enterprise/spaces/demo/view/candidates/cand%2F1')
  })

  it('posts only the outcome and the trimmed reason, and unwraps the result', async () => {
    vi.mocked(post).mockResolvedValue(ok(reviewResult()))
    await expect(decideReview('demo/space', 'cand/1', 'approve', '  核对无误 \n')).resolves.toEqual(reviewResult())
    expect(vi.mocked(post).mock.calls).toEqual([[
      '/api/v1/enterprise/spaces/demo%2Fspace/view/candidates/cand%2F1/decisions', { outcome: 'approve', reason: '核对无误' },
    ]])
  })

  it('keeps typed failures for every method', async () => {
    vi.mocked(get).mockRejectedValue({ status: 503, code: 'SERVICE_UNAVAILABLE' })
    await expect(listReviews('demo', 'pending')).rejects.toMatchObject({ status: 503, code: 'SERVICE_UNAVAILABLE' })
    await expect(readReview('demo', 'cand-1')).rejects.toBeInstanceOf(EnterpriseError)
    vi.mocked(post).mockRejectedValueOnce({ status: 409, code: 'NEEDS_REBASE' })
    const stale = decideReview('demo', 'cand-1', 'approve', 'ok')
    await expect(stale).rejects.toBeInstanceOf(EnterpriseError)
    await expect(stale).rejects.toMatchObject({ status: 409, code: 'NEEDS_REBASE' })
    const refusal = { success: false, code: 'DECISION_INVALID', $httpStatus: 400 }
    vi.mocked(post).mockResolvedValueOnce(refusal)
    await expect(decideReview('demo', 'cand-1', 'reject', 'x')).rejects.toMatchObject({ code: 'DECISION_INVALID' })
  })
})
