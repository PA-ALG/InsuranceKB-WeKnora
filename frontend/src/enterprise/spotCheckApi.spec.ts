import { afterEach, describe, expect, it, vi } from 'vitest'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))
import { get, post } from '@/utils/request'
import { EnterpriseError, listSamples, submitVerdict } from './enterpriseApi'
import { spotSample, spotVerdict } from './__tests__/spotCheckFixtures'
afterEach(() => vi.resetAllMocks())
const ok = (data: unknown) => ({ success: true, data, $httpStatus: 200 })

describe('spot-check session API', () => {
  it('encodes the Space, passes the status, and unwraps the sample list', async () => {
    vi.mocked(get).mockResolvedValue(ok({ samples: [spotSample()] }))
    await expect(listSamples('demo/space', 'pending')).resolves.toEqual([spotSample()])
    await listSamples('demo/space', 'decided')
    expect(vi.mocked(get).mock.calls.map(call => call[0])).toEqual([
      '/api/v1/enterprise/spaces/demo%2Fspace/view/samples?status=pending',
      '/api/v1/enterprise/spaces/demo%2Fspace/view/samples?status=decided',
    ])
  })
  it('posts only outcome and note through the session route and unwraps the verdict', async () => {
    vi.mocked(post).mockResolvedValue(ok({ verdict: spotVerdict() }))
    await expect(submitVerdict('demo/space', 'sample/id', 'incomplete', '补充条件')).resolves.toEqual(spotVerdict())
    expect(vi.mocked(post).mock.calls).toEqual([[
      '/api/v1/enterprise/spaces/demo%2Fspace/view/samples/sample%2Fid/verdicts', { outcome: 'incomplete', note: '补充条件' },
    ]])
  })
  it('keeps typed failures for both session methods', async () => {
    vi.mocked(get).mockRejectedValue({ status: 503, code: 'SERVICE_UNAVAILABLE' })
    await expect(listSamples('demo', 'pending')).rejects.toMatchObject({ status: 503, code: 'SERVICE_UNAVAILABLE' })
    vi.mocked(post).mockRejectedValueOnce({ status: 403, code: 'RELEASE_ACCESS_DENIED' })
    await expect(submitVerdict('demo', 'id', 'correct', '')).rejects.toBeInstanceOf(EnterpriseError)
    const refusal = { success: false, code: 'VERDICT_INVALID', $httpStatus: 400 }
    vi.mocked(post).mockResolvedValueOnce(refusal)
    await expect(submitVerdict('demo', 'id', 'wrong', '')).rejects.toMatchObject({ code: 'VERDICT_INVALID' })
  })
})
