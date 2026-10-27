// S5b-3d-2 acceptance (protected, written by Claude): the session route that returns a
// confirmation item's original file (Spec docs/design/slices/S5b-3d-2-待确认材料打开原文件.md §3).
import { afterEach, describe, expect, it, vi } from 'vitest'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))
import { get } from '@/utils/request'
import { EnterpriseError, readConfirmationFile } from './enterpriseApi'
afterEach(() => vi.resetAllMocks())

describe('confirmation file API', () => {
  it('reads the encoded item route as a blob through the authenticated client', async () => {
    const file = new Blob(['%PDF-1.7'], { type: 'application/pdf' })
    vi.mocked(get).mockResolvedValue(file as never)
    await expect(readConfirmationFile('demo/space', 'item/1')).resolves.toBe(file)
    const [url, config] = vi.mocked(get).mock.calls[0]
    expect(url).toBe('/api/v1/enterprise/spaces/demo%2Fspace/view/confirmations/item%2F1/file')
    expect(config).toMatchObject({ responseType: 'blob' })
  })

  it('keeps the typed failure the server returned', async () => {
    vi.mocked(get).mockRejectedValueOnce({ status: 404, code: 'SOURCE_NOT_FOUND' })
    const missing = readConfirmationFile('demo', 'item-1')
    await expect(missing).rejects.toBeInstanceOf(EnterpriseError)
    await expect(missing).rejects.toMatchObject({ status: 404, code: 'SOURCE_NOT_FOUND' })
    vi.mocked(get).mockRejectedValueOnce({ status: 409, code: 'SOURCE_INTEGRITY' })
    await expect(readConfirmationFile('demo', 'item-1')).rejects.toMatchObject({ code: 'SOURCE_INTEGRITY' })
  })

  it('refuses a success that is not a file', async () => {
    vi.mocked(get).mockResolvedValue({ success: true, data: {} } as never)
    await expect(readConfirmationFile('demo', 'item-1')).rejects.toBeInstanceOf(EnterpriseError)
  })
})
