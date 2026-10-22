// S9b acceptance (protected, written by Claude): an expert edit is one POST of exactly six keys
// to the session route; refusals keep their platform code and HTTP status
// (Spec docs/design/slices/S9b-专家编辑界面.md §2.1).
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))

type Api = typeof import('./enterpriseApi')
let api: Api
let post: ReturnType<typeof vi.fn>

const input = {
  base_release_id: 'rel-1', member_slug: 'P1/f_wait', base_member_digest: 'd'.repeat(64),
  state: 'present' as const, value: '180日', reason: '备案条款第五条',
}

beforeEach(async () => {
  vi.resetModules()
  post = vi.mocked((await import('@/utils/request')).post) as unknown as ReturnType<typeof vi.fn>
  post.mockReset()
  api = await import('./enterpriseApi')
})

describe('submitExpertEdit', () => {
  it('posts exactly the six keys to the Space session route and returns the new release', async () => {
    post.mockResolvedValue({ success: true, data: { release_id: 'rel-2', epoch: 2, revision_record_id: 'rev-1' } })
    const result = await api.submitExpertEdit('demo space', input)
    expect(post.mock.calls).toEqual([[
      '/api/v1/enterprise/spaces/demo%20space/view/expert-edits',
      {
        base_release_id: 'rel-1', member_slug: 'P1/f_wait', base_member_digest: 'd'.repeat(64),
        state: 'present', value: '180日', reason: '备案条款第五条',
      },
    ]])
    expect(Object.keys(post.mock.calls[0][1]).sort()).toEqual([
      'base_member_digest', 'base_release_id', 'member_slug', 'reason', 'state', 'value',
    ])
    expect(result).toEqual({ release_id: 'rel-2', epoch: 2, revision_record_id: 'rev-1' })
  })

  it.each([
    [{ success: false, code: 'EXPERT_EDIT_STALE', status: 409 }, 'EXPERT_EDIT_STALE', 409],
    [{ error: 'Forbidden: insufficient workspace role', status: 403 }, 'REQUEST_FAILED', 403],
  ])('keeps the refusal code and status', async (failure, code, status) => {
    post.mockRejectedValue(failure)
    const error = await api.submitExpertEdit('demo', input).catch(caught => caught)
    expect(error).toBeInstanceOf(api.EnterpriseError)
    expect(error.code).toBe(code)
    expect(error.status).toBe(status)
  })
})
