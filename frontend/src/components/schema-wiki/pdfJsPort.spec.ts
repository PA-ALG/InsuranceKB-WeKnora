// @vitest-environment happy-dom

import { expect, it, vi } from 'vitest'

import { createPdfJsPort, resolvePdfWorkerModuleUrl } from './pdfJsPort.ts'

it('uses a PDF module-worker cache key distinct from legacy MIME metadata', () => {
  expect(
    resolvePdfWorkerModuleUrl('/assets/pdf.worker.min-example.mjs'),
  ).toBe('/assets/pdf.worker.min-example.mjs?module-worker=mime-v1')
  expect(
    resolvePdfWorkerModuleUrl('/assets/pdf.worker.min-example.mjs?asset=1'),
  ).toBe('/assets/pdf.worker.min-example.mjs?asset=1&module-worker=mime-v1')
})


it('closes the PDF loading task after use and when document metadata is invalid', async () => {
  const destroy = vi.fn(async () => {})
  const loading = { promise: Promise.resolve({ numPages: 2, getPage: vi.fn() }), destroy }
  const port = createPdfJsPort({ getDocument: () => loading })
  const document = await port.open(new Uint8Array([1]))
  await document.close?.()
  expect(destroy).toHaveBeenCalledTimes(1)
  loading.promise = Promise.resolve({ numPages: 0, getPage: vi.fn() })
  await expect(port.open(new Uint8Array([1]))).rejects.toThrow('PDF_PREVIEW_UNAVAILABLE')
  expect(destroy).toHaveBeenCalledTimes(2)
})
