import { afterEach, describe, expect, it, vi } from 'vitest'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))
import { get } from '@/utils/request'
import { EnterpriseError, readConfirmationFile } from './enterpriseApi'
afterEach(() => vi.resetAllMocks())

describe('confirmation file request boundary', () => {
  it('passes the caller signal to the authenticated blob request', async () => {
    const controller = new AbortController(), blob = new Blob(['original'])
    vi.mocked(get).mockResolvedValue(blob as never)
    await expect(readConfirmationFile('space /?', 'item #?', controller.signal)).resolves.toBe(blob)
    expect(get).toHaveBeenCalledWith(
      '/api/v1/enterprise/spaces/space%20%2F%3F/view/confirmations/item%20%23%3F/file',
      { responseType: 'blob', signal: controller.signal },
    )
  })

  it.each([undefined, null, new Error('offline'), { code: '', status: '503' }])('normalizes untyped transport failures', async failure => {
    vi.mocked(get).mockRejectedValue(failure)
    await expect(readConfirmationFile('space', 'item')).rejects.toMatchObject({
      name: 'EnterpriseError', code: 'REQUEST_FAILED', status: undefined,
    })
  })

  it.each([undefined, null, 'not a blob', { success: true, data: {} }])('rejects non-file success payloads', async body => {
    vi.mocked(get).mockResolvedValue(body as never)
    await expect(readConfirmationFile('space', 'item')).rejects.toEqual(new EnterpriseError('INVALID_RESPONSE'))
  })
})
