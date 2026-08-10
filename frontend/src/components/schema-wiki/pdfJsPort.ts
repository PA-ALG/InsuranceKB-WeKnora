import {
  getDocument,
  GlobalWorkerOptions,
  type PDFDocumentProxy,
} from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

export interface RenderedPdfPage {
  readonly pageNumber: number
  readonly width: number
  readonly height: number
  readonly canvas: HTMLCanvasElement
}

export interface OpenedPdfDocument {
  readonly pageCount: number
  renderPage(pageNumber: number): Promise<RenderedPdfPage>
}

export interface PdfPort {
  open(bytes: Uint8Array): Promise<OpenedPdfDocument>
}

export interface PdfJsApi {
  getDocument(options: { data: Uint8Array }): {
    promise: Promise<Pick<PDFDocumentProxy, 'numPages' | 'getPage'>>
  }
}

const defaultPdfJsApi: PdfJsApi = { getDocument }

export function createPdfJsPort(api: PdfJsApi = defaultPdfJsApi): PdfPort {
  if (api === defaultPdfJsApi) {
    GlobalWorkerOptions.workerSrc = pdfWorkerUrl
  }
  return Object.freeze({
    async open(bytes: Uint8Array): Promise<OpenedPdfDocument> {
      if (!(bytes instanceof Uint8Array) || bytes.byteLength === 0) {
        throw new Error('PDF_PREVIEW_UNAVAILABLE')
      }
      const documentPort = await api.getDocument({ data: bytes.slice() }).promise
      if (!Number.isInteger(documentPort.numPages) || documentPort.numPages < 1) {
        throw new Error('PDF_PREVIEW_UNAVAILABLE')
      }
      return Object.freeze({
        pageCount: documentPort.numPages,
        async renderPage(pageNumber: number): Promise<RenderedPdfPage> {
          if (!Number.isInteger(pageNumber) || pageNumber < 1 || pageNumber > documentPort.numPages) {
            throw new Error('PAGE_UNAVAILABLE')
          }
          const page = await documentPort.getPage(pageNumber)
          const viewport = page.getViewport({ scale: 1 })
          if (
            !Number.isFinite(viewport.width) || viewport.width <= 0
            || !Number.isFinite(viewport.height) || viewport.height <= 0
          ) {
            throw new Error('PDF_PREVIEW_UNAVAILABLE')
          }
          const canvas = document.createElement('canvas')
          canvas.width = Math.ceil(viewport.width)
          canvas.height = Math.ceil(viewport.height)
          await page.render({ canvas, viewport }).promise
          return Object.freeze({
            pageNumber,
            width: viewport.width,
            height: viewport.height,
            canvas,
          })
        },
      })
    },
  })
}
