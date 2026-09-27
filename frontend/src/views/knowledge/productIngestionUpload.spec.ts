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
      kbId: { value: 'kb' }, productUploadChecking: { value: false },
      productIngestionEnabled: { value: false }, productIngestionRefresh: { value: 0 },
      kbInfo: { value: { name: 'Products' } },
      uploadTasksStore: { enqueue: vi.fn() },
      ROOT_FOLDER_PATH: '', buildUploadFileName: (file: File, folder: string) => `${folder}${file.name}`,
      uploadProductBatchIfEnabled: vi.fn(), getProductIngestionEnabled: vi.fn(),
      executeProductUploadBatch: vi.fn(), ensureDocumentKbReady: vi.fn(), openUploadConfirmDialog: vi.fn(),
      showUploadResultMessages: vi.fn(), MessagePlugin: { error: vi.fn(), warning: vi.fn(), success: vi.fn() }, t: (key: string) => key,
    }
  })
  it('passes the entire original batch to the platform and never per-file upload', async () => {
    ports.uploadProductBatchIfEnabled.mockResolvedValue({ run_id: 'r', accepted_file_count: 3, rejected_file_count: 0 })
    const files = ['a', 'b', 'c'].map(name => new File(['original'], `${name}.pdf`))
    expect(await action('executeProductUploadBatch', ports)(files)).toEqual({ successCount: 3, failCount: 0 })
    expect(ports.uploadProductBatchIfEnabled).toHaveBeenCalledWith('kb', files)
    expect(ports.uploadTasksStore.enqueue).not.toHaveBeenCalled()
    expect(ports.productIngestionRefresh.value).toBe(1)
  })
  it('hands disabled-capability uploads to the native global queue with their options', async () => {
    const file = new File(['original'], 'a.pdf')
    const processConfig = { foo: true }
    action('enqueueUploads', ports)([file], { processConfig, tagIds: ['tag'], targetFolder: 'folder/' })
    expect(ports.uploadTasksStore.enqueue).toHaveBeenCalledWith({
      kbId: 'kb', kbName: 'Products', targetFolder: 'folder/', tagIds: ['tag'], processConfig,
      uploads: [{ file, fileName: 'folder/a.pdf' }],
    })
    expect(ports.uploadProductBatchIfEnabled).not.toHaveBeenCalled()
  })
  it('never falls back or reuploads after an uncertain platform response', async () => {
    ports.uploadProductBatchIfEnabled.mockRejectedValue(new Error('timeout'))
    await action('executeProductUploadBatch', ports)([new File(['x'], 'a.pdf')])
    expect(ports.uploadTasksStore.enqueue).not.toHaveBeenCalled()
    expect(ports.MessagePlugin.error).toHaveBeenCalledTimes(1)
  })
  it('enabled file selection goes directly to server upload without browser processing configuration', async () => {
    ports.executeProductUploadBatch.mockResolvedValue({ successCount: 1, failCount: 0 })
    const files = [new File(['x'], 'a.pdf')]
    await action('handleUploadSourceFiles', ports)(files)
    expect(ports.executeProductUploadBatch).toHaveBeenCalledWith(files)
    expect(ports.ensureDocumentKbReady).not.toHaveBeenCalled()
    expect(ports.openUploadConfirmDialog).not.toHaveBeenCalled()
  })
  it('uses one capability decision and preserves native upload on an explicit disabled result', async () => {
    ports.getProductIngestionEnabled.mockResolvedValue(true)
    ports.executeProductUploadBatch.mockResolvedValue(null)
    ports.ensureDocumentKbReady.mockReturnValue(true)
    const files = [new File(['x'], 'a.pdf')]
    await action('handleUploadSourceFiles', ports)(files)
    expect(ports.executeProductUploadBatch).toHaveBeenCalledWith(files)
    expect(ports.getProductIngestionEnabled).not.toHaveBeenCalled()
    expect(ports.openUploadConfirmDialog).toHaveBeenCalledWith(files)
  })
  it('reports a busy submission instead of silently discarding another selected batch', async () => {
    ports.productUploadChecking.value = true
    await action('handleUploadSourceFiles', ports)([new File(['x'], 'second.pdf')])
    expect(ports.MessagePlugin.warning).toHaveBeenCalledTimes(1)
    expect(ports.executeProductUploadBatch).not.toHaveBeenCalled()
  })
  it('disabled file selection preserves the old readiness check and dialog', async () => {
    ports.executeProductUploadBatch.mockResolvedValue(null)
    ports.ensureDocumentKbReady.mockReturnValue(true)
    const files = [new File(['x'], 'a.pdf')]
    await action('handleUploadSourceFiles', ports)(files)
    expect(ports.openUploadConfirmDialog).toHaveBeenCalledWith(files)
    expect(ports.executeProductUploadBatch).toHaveBeenCalledWith(files)
  })
})
