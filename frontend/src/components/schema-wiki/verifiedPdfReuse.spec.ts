// @vitest-environment happy-dom
import { createHash, webcrypto } from 'node:crypto'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { createVerifiedPdfReuse } from './verifiedPdfReuse'
const bytes = new TextEncoder().encode('%PDF-verified-source')
const hash = createHash('sha256').update(bytes).digest('hex')
beforeAll(() => { Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true }) })
function fixture(maxBytes = 16 * 1024 * 1024) {
  const closed = vi.fn()
  const document = { pageCount: 4, renderPage: vi.fn(), close: closed }
  const open = vi.fn().mockResolvedValue(document)
  const load = vi.fn().mockResolvedValue(bytes)
  return { cache: createVerifiedPdfReuse({ open }, maxBytes), open, load, document, closed }
}
describe('bounded verified PDF reuse', () => {
  it('reuses one verified document for two citations without downloading or opening it again', async () => {
    const f = fixture()
    const first = await f.cache.acquire('scope/release/source/binding', hash, 4, f.load)
    first.release()
    const next = await f.cache.acquire('scope/release/source/binding', hash, 4, f.load)
    expect(next.document).toBe(first.document)
    expect(f.load).toHaveBeenCalledTimes(1); expect(f.open).toHaveBeenCalledTimes(1)
    next.release(); f.cache.clear(); expect(f.closed).toHaveBeenCalledTimes(1)
  })
  it('replaces a different source identity and waits for the prior viewer to release it', async () => {
    const f = fixture()
    const first = await f.cache.acquire('release-a/source', hash, 4, f.load)
    const next = await f.cache.acquire('release-b/source', hash, 4, f.load)
    expect(f.load).toHaveBeenCalledTimes(2)
    expect(f.closed).not.toHaveBeenCalled()
    first.release(); expect(f.closed).toHaveBeenCalledTimes(1)
    next.release(); f.cache.clear(); expect(f.closed).toHaveBeenCalledTimes(2)
  })
  it('does not retain oversized files after the viewer closes', async () => {
    const f = fixture(1)
    const first = await f.cache.acquire('source', hash, 4, f.load); first.release()
    const second = await f.cache.acquire('source', hash, 4, f.load); second.release()
    expect(f.load).toHaveBeenCalledTimes(2); expect(f.closed).toHaveBeenCalledTimes(2)
  })
  it('does not cache bad bytes or page counts', async () => {
    const f = fixture()
    f.load.mockResolvedValueOnce(new Uint8Array([0]))
    await expect(f.cache.acquire('source', hash, 4, f.load)).rejects.toThrow('PREVIEW_BYTES_HASH_MISMATCH')
    expect(f.open).not.toHaveBeenCalled()
    await expect(f.cache.acquire('source', hash, 5, f.load)).rejects.toThrow('PAGE_UNAVAILABLE')
    expect(f.closed).toHaveBeenCalledTimes(1)
    const good = await f.cache.acquire('source', hash, 4, f.load); good.release()
    expect(f.load).toHaveBeenCalledTimes(3)
  })
  it('does not let an in-flight open repopulate a cleared reader', async () => {
    const f = fixture(); let finish!: (value: typeof f.document) => void
    f.open.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const pending = f.cache.acquire('source', hash, 4, f.load)
    const rejected = expect(pending).rejects.toThrow('PDF_PREVIEW_STALE')
    await vi.waitFor(() => expect(f.open).toHaveBeenCalled())
    f.cache.clear(); finish(f.document); await rejected
    expect(f.closed).toHaveBeenCalledTimes(1)
    const good = await f.cache.acquire('source', hash, 4, f.load); good.release()
    expect(f.load).toHaveBeenCalledTimes(2)
  })
})
