import { afterEach, expect, it, vi } from 'vitest'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))
import { post } from '@/utils/request'
import { decideReview, EnterpriseError } from './enterpriseApi'
afterEach(() => vi.resetAllMocks())
it('preserves HTTP status on a refused decision envelope', async () => {
  const denied = { success: false, code: 'RELEASE_ACCESS_DENIED', $httpStatus: 403 }
  vi.mocked(post).mockResolvedValue(denied)
  const result = decideReview('space', 'candidate', 'approve', 'reason')
  await expect(result).rejects.toBeInstanceOf(EnterpriseError)
  await expect(result).rejects.toMatchObject({ code: 'RELEASE_ACCESS_DENIED', status: 403 })
})
