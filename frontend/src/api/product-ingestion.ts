import { get, post, postUpload } from '@/utils/request'

export type ProductRunState = 'created' | 'uploading' | 'accepting_uploads' | 'processing' | 'running' | 'waiting_sources' | 'awaiting_sources' | 'succeeded' | 'partial_success' | 'failed' | 'needs_confirmation'
export interface ProductCounts {
  success_count?: number | null
  missing_count?: number | null
  failure_count?: number | null
}
export interface ProductStage extends ProductCounts {
  name: string
  state: string
  started_at?: string | null
  finished_at?: string | null
}
export interface ProductFieldStatus {
  field_key: string
  outcome: 'verified' | 'not_provided' | 'extraction_failed'
  reason?: string | null
}
export interface ProductSourcePhase {
  phase: string
  recorded: boolean
  occurrences: { occurrence: number; status: string; started_at_unix_ms: number; finished_at_unix_ms: number; duration_ms: number }[]
}
export interface ProductDiscoverySummary {
  state: 'NOT_EXECUTED' | 'FAILED' | 'PENDING' | 'REJECTED' | 'EMPTY' | 'ACCEPTED'
  reused: boolean
  reason_codes: string[]
  counts: { proposed_new: number | null; duplicate: number | null; update_proposal: number | null; rejected: number | null; published: number | null }
  coverage: { offered_chars: number; omitted_chars: number; complete: boolean; material_count: number } | null
  published_confirmed: boolean
}
export interface ProductIngestionRun {
  run_id: string
  wiki_knowledge_base_id?: string | null
  state: ProductRunState
  stage?: string | null
  stages?: ProductStage[]
  counts?: ProductCounts
  model_call_count?: number | null
  model_call_count_complete?: boolean
  source_processing?: { materials: { knowledge_id: string; file_name?: string; reused: boolean; availability: string; counts?: { attempts: number } | null; phases: ProductSourcePhase[] }[] }
  discovery_summary?: ProductDiscoverySummary
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  published_url?: string | null
  reason?: string | null
  fields?: ProductFieldStatus[]
}
export interface ProductUploadReceipt {
  run_id: string
  accepted_file_count: number
  rejected_file_count: number
}
interface Envelope<T> { success: boolean; data: T }
const base = (kbId: string) => `/api/v1/knowledge-bases/${encodeURIComponent(kbId)}/product-ingestions`
function unwrap<T>(response: Envelope<T>): T {
  if (response?.success !== true || response.data == null) throw new Error('平台未返回有效的产品任务结果')
  return response.data
}

export async function getProductIngestionEnabled(kbId: string): Promise<boolean> {
  try {
    const response = await get<Envelope<{ enabled?: boolean }>>(`${base(kbId)}/capabilities`)
    return unwrap(response).enabled === true
  } catch (error: any) {
    if (error?.status === 404) return false
    throw error
  }
}

/** Null alone authorizes the caller to keep the existing, disabled-feature upload path. */
export async function uploadProductBatchIfEnabled(kbId: string, files: File[]): Promise<ProductUploadReceipt | null> {
  if (!await getProductIngestionEnabled(kbId)) return null
  const body = new FormData()
  files.forEach(file => body.append('files', file))
  return unwrap<ProductUploadReceipt>(await postUpload(`${base(kbId)}/uploads`, body))
}

export async function listProductIngestions(kbId: string): Promise<ProductIngestionRun[]> {
  return unwrap(await get<Envelope<{ runs: ProductIngestionRun[] }>>(base(kbId))).runs
}
export async function getProductIngestion(kbId: string, runId: string): Promise<ProductIngestionRun> {
  return unwrap(await get<Envelope<ProductIngestionRun>>(`${base(kbId)}/${encodeURIComponent(runId)}`))
}
export async function retryProductFields(kbId: string, runId: string, fieldKeys: string[]): Promise<ProductIngestionRun> {
  return unwrap(await post<Envelope<ProductIngestionRun>>(`${base(kbId)}/${encodeURIComponent(runId)}/retry-fields`, { field_keys: fieldKeys }))
}
