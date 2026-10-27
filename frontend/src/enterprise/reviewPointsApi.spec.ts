// RV6c acceptance (protected, written by Claude): the RV6b session route that records a person's
// decision on review points, and the removal of the whole-candidate decision from the page's API
// (Spec docs/design/slices/RV6c-逐字段审核页面与首页工作台.md §1.5).
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))

import { get, post } from '@/utils/request'
import * as api from './enterpriseApi'
import { decidePoints, EnterpriseError, readReview } from './enterpriseApi'
import { pointDetail, pointResult } from './__tests__/reviewPointFixtures'

afterEach(() => vi.resetAllMocks())
const ok = (data: unknown) => ({ success: true, data, $httpStatus: 200 })

describe('review point API', () => {
  it('posts only the slugs, the outcome and the trimmed reason to the encoded point route', async () => {
    vi.mocked(post).mockResolvedValue(ok(pointResult(['M1/waiting_period', 'entity/M1'], 'released')))
    await expect(decidePoints('demo/space', 'cand/1', ['M1/waiting_period', 'entity/M1'], 'approve', '  核对无误 \n'))
      .resolves.toEqual(pointResult(['M1/waiting_period', 'entity/M1'], 'released'))
    expect(vi.mocked(post).mock.calls).toEqual([[
      '/api/v1/enterprise/spaces/demo%2Fspace/view/candidates/cand%2F1/points/decisions',
      { slugs: ['M1/waiting_period', 'entity/M1'], outcome: 'approve', reason: '核对无误' },
    ]])
  })

  it('sends a rejection with its reason', async () => {
    vi.mocked(post).mockResolvedValue(ok(pointResult(['M2/waiting_period'], 'rejected')))
    await decidePoints('demo', 'cand-1', ['M2/waiting_period'], 'reject', '取值与条款不符')
    expect(vi.mocked(post).mock.calls[0][1]).toEqual({ slugs: ['M2/waiting_period'], outcome: 'reject', reason: '取值与条款不符' })
  })

  it('keeps typed failures with their status', async () => {
    vi.mocked(post).mockRejectedValueOnce({ status: 409, code: 'MEMBER_DECIDED' })
    const decided = decidePoints('demo', 'cand-1', ['M1/waiting_period'], 'approve', 'ok')
    await expect(decided).rejects.toBeInstanceOf(EnterpriseError)
    await expect(decided).rejects.toMatchObject({ status: 409, code: 'MEMBER_DECIDED' })
    const refusal = { success: false, code: 'DECISION_INVALID', $httpStatus: 400 }
    vi.mocked(post).mockResolvedValueOnce(refusal)
    await expect(decidePoints('demo', 'cand-1', ['x'], 'reject', 'x')).rejects.toMatchObject({ code: 'DECISION_INVALID', status: 400 })
  })

  it('reads a candidate with its review points unchanged', async () => {
    vi.mocked(get).mockResolvedValue(ok(pointDetail()))
    await expect(readReview('demo', 'cand-1')).resolves.toEqual(pointDetail())
  })

  it('no longer offers a whole-candidate decision', () => {
    expect('decideReview' in api).toBe(false)
  })
})
