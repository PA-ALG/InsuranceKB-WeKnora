import type { OpenedPdfDocument, PdfPort } from './pdfJsPort'
import { conceptSHA256830G2 } from './conceptCitationAuthority830G2'

export interface VerifiedPdfLease { readonly document: OpenedPdfDocument; release(): void }
interface Entry { key: string; document: OpenedPdfDocument; users: number; retained: boolean; closed: boolean }

// Owned by one mounted reader. The caller must obtain fresh, validated citation
// authority before each acquire; this cache never authorizes a source read.
export function createVerifiedPdfReuse(pdfPort: PdfPort, maxBytes = 16 * 1024 * 1024) {
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 0) throw new Error('PDF_CACHE_LIMIT_INVALID')
  let current: Entry | null = null
  let generation = 0
  let pending: { key: string; promise: Promise<Entry> } | null = null
  function dispose(entry: Entry) {
    if (entry.closed || entry.retained || entry.users) return
    entry.closed = true
    if (current === entry) current = null
    // A failed resource cleanup must not turn into an unhandled rejection.
    try { void Promise.resolve(entry.document.close?.()).catch(() => {}) } catch { /* already retired */ }
  }
  function retire() {
    if (current) { current.retained = false; dispose(current); current = null }
  }
  function lease(entry: Entry): VerifiedPdfLease {
    if (entry.closed) throw new Error('PDF_PREVIEW_STALE')
    entry.users++
    let released = false
    return { document: entry.document, release() {
      if (released) return
      released = true; entry.users--; dispose(entry)
    } }
  }
  return {
    clear() { generation++; pending = null; retire() },
    async acquire(sourceKey: string, hash: string, pageCount: number, load: () => Promise<Uint8Array>): Promise<VerifiedPdfLease> {
      const key = JSON.stringify([sourceKey, hash, pageCount])
      if (current?.retained && current.key === key) return lease(current)
      let task = pending?.key === key ? pending.promise : null
      if (!task) {
        const version = ++generation
        retire()
        task = (async () => {
          const bytes = await load()
          if (!(bytes instanceof Uint8Array) || bytes.length === 0 || await conceptSHA256830G2(bytes) !== hash) {
            throw new Error('PREVIEW_BYTES_HASH_MISMATCH')
          }
          if (version !== generation) throw new Error('PDF_PREVIEW_STALE')
          const document = await pdfPort.open(bytes.slice())
          const entry: Entry = { key, document, users: 0, retained: false, closed: false }
          if (document.pageCount !== pageCount) { dispose(entry); throw new Error('PAGE_UNAVAILABLE') }
          if (version !== generation) { dispose(entry); throw new Error('PDF_PREVIEW_STALE') }
          entry.retained = bytes.byteLength <= maxBytes
          current = entry
          return entry
        })()
        pending = { key, promise: task }
      }
      try {
        const entry = await task
        if (current !== entry) throw new Error('PDF_PREVIEW_STALE')
        return lease(entry)
      } finally {
        if (pending?.promise === task) pending = null
      }
    },
  }
}
export type VerifiedPdfReuse = ReturnType<typeof createVerifiedPdfReuse>
