// @vitest-environment happy-dom

import { expect, it } from 'vitest'

import { resolvePdfWorkerModuleUrl } from './pdfJsPort.ts'

it('uses a PDF module-worker cache key distinct from legacy MIME metadata', () => {
  expect(
    resolvePdfWorkerModuleUrl('/assets/pdf.worker.min-example.mjs'),
  ).toBe('/assets/pdf.worker.min-example.mjs?module-worker=mime-v1')
  expect(
    resolvePdfWorkerModuleUrl('/assets/pdf.worker.min-example.mjs?asset=1'),
  ).toBe('/assets/pdf.worker.min-example.mjs?asset=1&module-worker=mime-v1')
})
