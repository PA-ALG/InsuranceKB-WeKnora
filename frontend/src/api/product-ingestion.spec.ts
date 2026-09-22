// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postUpload: vi.fn() }))
vi.mock('@/utils/request', () => http)
const modules = import.meta.glob('./product-ingestion.ts')
async function api(): Promise<any> {
  expect(modules['./product-ingestion.ts'], 'product ingestion API must exist').toBeTypeOf('function')
  return modules['./product-ingestion.ts']!()
}

describe('platform product ingestion API', () => {
  beforeEach(() => vi.resetAllMocks())
  it('sends one multipart batch containing only repeated original files', async () => {
    const client = await api()
    http.get.mockResolvedValue({ success: true, data: { enabled: true } })
    http.postUpload.mockResolvedValue({ success: true, data: { run_id: 'run-1', accepted_file_count: 3, rejected_file_count: 0 } })
    const files = ['条款.pdf', '说明书.pdf', '费率.pdf'].map(name => new File(['original'], name))
    const result = await client.uploadProductBatchIfEnabled('kb/1', files)
    expect(result.run_id).toBe('run-1')
    expect(http.postUpload).toHaveBeenCalledTimes(1)
    const [url, form] = http.postUpload.mock.calls[0]!
    expect(url).toBe('/api/v1/knowledge-bases/kb%2F1/product-ingestions/uploads')
    expect([...form.keys()]).toEqual(['files', 'files', 'files'])
    expect(form.getAll('files')).toEqual(files)
    expect(http.post).not.toHaveBeenCalled()
  })
  it.each([false, undefined])('keeps existing upload when capability is %s', async enabled => {
    const client = await api()
    http.get.mockResolvedValue({ success: true, data: { enabled } })
    expect(await client.uploadProductBatchIfEnabled('kb', [new File(['x'], 'x.pdf')])).toBeNull()
    expect(http.postUpload).not.toHaveBeenCalled()
  })
  it('treats an absent endpoint as disabled but does not hide authorization/network failures', async () => {
    const client = await api()
    http.get.mockRejectedValueOnce({ status: 404 }).mockRejectedValueOnce({ status: 403 })
    expect(await client.getProductIngestionEnabled('kb')).toBe(false)
    await expect(client.getProductIngestionEnabled('kb')).rejects.toEqual({ status: 403 })
  })
  it('does not retry or fall back after a server upload fails', async () => {
    const client = await api()
    http.get.mockResolvedValue({ success: true, data: { enabled: true } })
    http.postUpload.mockRejectedValue(new Error('connection lost'))
    await expect(client.uploadProductBatchIfEnabled('kb', [new File(['x'], 'x.pdf')])).rejects.toThrow()
    expect(http.postUpload).toHaveBeenCalledTimes(1)
  })
  it('reads persisted runs and starts only a selected field retry', async () => {
    const client = await api()
    http.get.mockResolvedValueOnce({ success: true, data: { runs: [] } }).mockResolvedValueOnce({ success: true, data: { run_id: 'r' } })
    expect(await client.listProductIngestions('kb')).toEqual([])
    await client.getProductIngestion('kb', 'r/1')
    expect(http.get).toHaveBeenLastCalledWith('/api/v1/knowledge-bases/kb/product-ingestions/r%2F1')
    http.post.mockResolvedValue({ success: true, data: { run_id: 'new' } })
    expect((await client.retryProductFields('kb', 'r', ['premium'])).run_id).toBe('new')
    expect(http.post).toHaveBeenCalledWith('/api/v1/knowledge-bases/kb/product-ingestions/r/retry-fields', { field_keys: ['premium'] })
  })
  it('requests source recovery with only the observed run version and no automatic resend', async () => {
    const client = await api()
    http.post.mockResolvedValueOnce({ success: true, data: { run_id: 'child' } }).mockRejectedValueOnce(new Error('unknown response'))
    expect((await client.retryProductProcessing('kb', 'r/1', 7)).run_id).toBe('child')
    expect(http.post).toHaveBeenCalledWith('/api/v1/knowledge-bases/kb/product-ingestions/r%2F1/retry-processing', { expected_version: 7 })
    await expect(client.retryProductProcessing('kb', 'r/1', 7)).rejects.toThrow('unknown response')
    expect(http.post).toHaveBeenCalledTimes(2)
  })

})
