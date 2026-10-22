// S7b acceptance (protected, written by Claude): the 830-era Schema Wiki frontend is removed —
// its pages, API adapters and citation viewers, its routes and the knowledge base tab — while the
// pdf.js port the enterprise source viewer needs lives on in the enterprise package
// (Spec docs/design/slices/S7b-删除旧版SchemaWiki前端.md §4).
import { describe, expect, it } from 'vitest'
import routerSource from '@/router/index.ts?raw'
import knowledgeBaseSource from '@/views/knowledge/KnowledgeBase.vue?raw'
import sourcePageViewerSource from './SourcePageViewer.vue?raw'

const legacy = {
  ...import.meta.glob('/src/views/knowledge/schema-wiki/**/*.{ts,vue}'),
  ...import.meta.glob('/src/api/schema-wiki/**/*.{ts,vue}'),
  ...import.meta.glob('/src/components/schema-wiki/**/*.{ts,vue}'),
}
const port = import.meta.glob<{ createPdfJsPort?: unknown }>('./pdfJsPort.ts', { eager: true })

describe('the 830-era Schema Wiki frontend', () => {
  it('leaves no source file in the three legacy directories', () => {
    expect(Object.keys(legacy)).toEqual([])
  })

  it('registers no schema-wiki route', () => {
    expect(routerSource).not.toContain('schema-wiki')
  })

  it('leaves knowledge bases without a schema tab, opening on documents', () => {
    expect(knowledgeBaseSource).not.toContain('schema-wiki/')
    expect(knowledgeBaseSource).toContain("const validTabs = ['materials', 'documents', 'graph'] as const")
    expect(knowledgeBaseSource).toMatch(/const initTab = [^\n]*: 'documents'\n/)
    expect(knowledgeBaseSource).not.toMatch(/activeKbTab === 'schema'/)
  })
})

describe('the pdf.js port of the enterprise source viewer', () => {
  it('lives in the enterprise package', () => {
    expect(typeof port['./pdfJsPort.ts']?.createPdfJsPort).toBe('function')
    expect(sourcePageViewerSource).toContain("from './pdfJsPort'")
    expect(sourcePageViewerSource).not.toContain('schema-wiki')
  })
})
