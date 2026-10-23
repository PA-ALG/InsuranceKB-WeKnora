// S7d-2a acceptance (protected, written by Claude): the knowledge base page no longer asks the
// retired product-ingestion service before an upload; uploads open the native dialog as upstream
// does (Spec docs/design/slices/S7d-2a-删除产品导入桥与面板.md §4).
import { describe, expect, it } from 'vitest'
import knowledgeBaseSource from '@/views/knowledge/KnowledgeBase.vue?raw'

const removed = {
  ...import.meta.glob('/src/api/product-ingestion*'),
  ...import.meta.glob('/src/components/knowledge-base/product-ingestion-status*'),
}

describe('the product-ingestion frontend', () => {
  it('leaves no API client or status panel', () => {
    expect(Object.keys(removed)).toEqual([])
  })

  it('is no longer referenced by the knowledge base page', () => {
    for (const name of ['product-ingestion', 'ProductIngestion', 'uploadProductBatchIfEnabled']) {
      expect(knowledgeBaseSource).not.toContain(name)
    }
  })

  it('opens the native upload dialog directly, as upstream does', () => {
    expect(knowledgeBaseSource).toContain([
      'const handleUploadSourceFiles = (files: File[]) => {',
      '  if (!ensureDocumentKbReady()) return;',
      '  if (files.length === 0) return;',
      '  openUploadConfirmDialog(files);',
      '};',
    ].join('\n'))
  })
})
