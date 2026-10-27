// RV5b acceptance (protected, written by Claude): the RV5a session routes that list a Space's
// candidates and read one (Spec docs/design/slices/RV5b-人工审核队列页面.md §2). RV6c removed the
// whole-candidate decision; point decisions are in reviewPointsApi.spec.ts.
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))

import { get } from '@/utils/request'
import { EnterpriseError, listReviews, readReview } from './enterpriseApi'
import { reviewDetail, reviewItem } from './__tests__/reviewFixtures'

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

  it('keeps typed failures for every method', async () => {
    vi.mocked(get).mockRejectedValue({ status: 503, code: 'SERVICE_UNAVAILABLE' })
    await expect(listReviews('demo', 'pending')).rejects.toMatchObject({ status: 503, code: 'SERVICE_UNAVAILABLE' })
    await expect(readReview('demo', 'cand-1')).rejects.toBeInstanceOf(EnterpriseError)
  })
})
