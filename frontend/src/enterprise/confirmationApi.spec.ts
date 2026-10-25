// S5b-3b acceptance (protected, written by Claude): the session routes of S5b-3a that list a
// Space's confirmation items and record a person's answer (Spec docs/design/slices/S5b-3b-待确认材料页面.md §2.1).
import { afterEach, describe, expect, it, vi } from 'vitest'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))
import { get, post } from '@/utils/request'
import { answerConfirmation, EnterpriseError, listConfirmations } from './enterpriseApi'
import { confirmationAnswer, confirmationItem } from './__tests__/confirmationFixtures'
afterEach(() => vi.resetAllMocks())
const ok = (data: unknown) => ({ success: true, data, $httpStatus: 200 })

describe('confirmation session API', () => {
  it('encodes the Space, passes the status, and unwraps the items', async () => {
    vi.mocked(get).mockResolvedValue(ok({ items: [confirmationItem()] }))
    await expect(listConfirmations('demo/space', 'open')).resolves.toEqual([confirmationItem()])
    await listConfirmations('demo/space', 'closed')
    expect(vi.mocked(get).mock.calls.map(call => call[0])).toEqual([
      '/api/v1/enterprise/spaces/demo%2Fspace/view/confirmations?status=open',
      '/api/v1/enterprise/spaces/demo%2Fspace/view/confirmations?status=closed',
    ])
  })

  it('posts only the option key and note through the session route and unwraps the answer', async () => {
    vi.mocked(post).mockResolvedValue(ok({ answer: confirmationAnswer('item/1') }))
    await expect(answerConfirmation('demo/space', 'item/1', 'supplement', '保留两份'))
      .resolves.toEqual(confirmationAnswer('item/1'))
    expect(vi.mocked(post).mock.calls).toEqual([[
      '/api/v1/enterprise/spaces/demo%2Fspace/view/confirmations/item%2F1/answers', { option_key: 'supplement', note: '保留两份' },
    ]])
  })

  it('keeps typed failures for both session methods', async () => {
    vi.mocked(get).mockRejectedValue({ status: 503, code: 'SERVICE_UNAVAILABLE' })
    await expect(listConfirmations('demo', 'open')).rejects.toMatchObject({ status: 503, code: 'SERVICE_UNAVAILABLE' })
    vi.mocked(post).mockRejectedValueOnce({ status: 409, code: 'CONFIRMATION_CLOSED' })
    const closed = answerConfirmation('demo', 'id', 'ignore', '')
    await expect(closed).rejects.toBeInstanceOf(EnterpriseError)
    await expect(closed).rejects.toMatchObject({ status: 409, code: 'CONFIRMATION_CLOSED' })
    vi.mocked(post).mockResolvedValueOnce({ success: false, code: 'ANSWER_INVALID', $httpStatus: 400 })
    await expect(answerConfirmation('demo', 'id', 'unknown', '')).rejects.toMatchObject({ code: 'ANSWER_INVALID' })
  })
})
