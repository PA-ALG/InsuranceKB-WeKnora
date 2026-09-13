// @vitest-environment happy-dom
import { parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import knowledgeBaseSource from './KnowledgeBase.vue?raw'

// Exercise the original SFC actions with injected ports, without mounting its unrelated editors.
const script = parse(knowledgeBaseSource).descriptor.scriptSetup!.content
function action(name: string, ports: Record<string, unknown>): (...args: any[]) => Promise<any> {
  const ast = ts.createSourceFile('KnowledgeBase.ts', script, ts.ScriptTarget.Latest, true)
  let initializer: ts.Expression | undefined
  ast.forEachChild(node => {
    if (ts.isVariableStatement(node)) {
      for (const declaration of node.declarationList.declarations) {
        if (declaration.name.getText(ast) === name) initializer = declaration.initializer
      }
    }
  })
  expect(initializer, `original ${name} action exists`).toBeDefined()
  const javascript = ts.transpileModule(`const action = ${initializer!.getText(ast)};`, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  return new Function(...Object.keys(ports), `${javascript}; return action;`)(...Object.values(ports))
}

describe('knowledge base product upload wiring', () => {
  let ports: Record<string, any>
  beforeEach(() => {
    ports = {
      kbId: { value: 'kb' }, uploading: { value: false },
      productIngestionEnabled: { value: false }, productIngestionRefresh: { value: 0 },
      selectedTagIds: { value: ['tag'] }, getFolderUploadFileName: () => undefined,
      uploadProductBatchIfEnabled: vi.fn(), uploadKnowledgeFile: vi.fn(), getProductIngestionEnabled: vi.fn(),
      executeUploadBatch: vi.fn(), ensureDocumentKbReady: vi.fn(), openUploadConfirmDialog: vi.fn(),
      showUploadResultMessages: vi.fn(), MessagePlugin: { error: vi.fn(), warning: vi.fn(), success: vi.fn() }, t: (key: string) => key,
    }
  })
  it('passes the entire original batch to the platform and never per-file upload', async () => {
    ports.uploadProductBatchIfEnabled.mockResolvedValue({ run_id: 'r', accepted_file_count: 3, rejected_file_count: 0 })
    const files = ['a', 'b', 'c'].map(name => new File(['original'], `${name}.pdf`))
    expect(await action('executeUploadBatch', ports)(files, { processConfig: { ignored: true } })).toEqual({ successCount: 3, failCount: 0 })
    expect(ports.uploadProductBatchIfEnabled).toHaveBeenCalledWith('kb', files)
    expect(ports.uploadKnowledgeFile).not.toHaveBeenCalled()
    expect(ports.productIngestionRefresh.value).toBe(1)
  })
  it('retains existing upload options only when capability is disabled', async () => {
    ports.uploadProductBatchIfEnabled.mockResolvedValue(null)
    ports.uploadKnowledgeFile.mockResolvedValue({ success: true })
    const file = new File(['original'], 'a.pdf')
    const processConfig = { foo: true }
    await action('executeUploadBatch', ports)([file], { processConfig })
    expect(ports.uploadKnowledgeFile).toHaveBeenCalledWith('kb', { file, tag_ids: ['tag'], process_config: processConfig })
  })
  it('never falls back or reuploads after an uncertain platform response', async () => {
    ports.uploadProductBatchIfEnabled.mockRejectedValue(new Error('timeout'))
    await action('executeUploadBatch', ports)([new File(['x'], 'a.pdf')])
    expect(ports.uploadKnowledgeFile).not.toHaveBeenCalled()
    expect(ports.MessagePlugin.error).toHaveBeenCalledTimes(1)
  })
  it('enabled file selection goes directly to server upload without browser processing configuration', async () => {
    ports.getProductIngestionEnabled.mockResolvedValue(true)
    const files = [new File(['x'], 'a.pdf')]
    await action('handleUploadSourceFiles', ports)(files)
    expect(ports.executeUploadBatch).toHaveBeenCalledWith(files)
    expect(ports.ensureDocumentKbReady).not.toHaveBeenCalled()
    expect(ports.openUploadConfirmDialog).not.toHaveBeenCalled()
  })
  it('disabled file selection preserves the old readiness check and dialog', async () => {
    ports.getProductIngestionEnabled.mockResolvedValue(false)
    ports.ensureDocumentKbReady.mockReturnValue(true)
    const files = [new File(['x'], 'a.pdf')]
    await action('handleUploadSourceFiles', ports)(files)
    expect(ports.openUploadConfirmDialog).toHaveBeenCalledWith(files)
    expect(ports.executeUploadBatch).not.toHaveBeenCalled()
  })
})
