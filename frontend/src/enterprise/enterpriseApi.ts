import { markRaw } from 'vue'
import { get, post } from '@/utils/request'
import { trimReviewReason } from './reviewReason'

// Session routes of the enterprise platform. Bodies are `{success, data}`;
// refusals carry a platform `code`, which callers branch on through EnterpriseError.

export interface ReleaseMember {
  kind: string
  logical_slug: string
  payload: Record<string, unknown>
  member_digest: string
  evidence_refs?: string[]
  access_scope: string
}

export interface Release {
  id: string
  epoch: number
  base_release_id?: string
  members: ReleaseMember[]
}

export interface Citation {
  release_id: string
  member: string
  evidence_index: number
  origin: string
  source: { knowledge_id: string; parse_attempt: number; document: string; file_sha256: string }
  // Office pages have no geometry: only `number` (S11d).
  page: { number: number; width_points?: string; height_points?: string }
  start: number
  end: number
  quote: string
  /** PDF evidence only. */
  highlight?: { coordinate_space: string; complete: boolean; rects: [number, number, number, number][] }
  /** Office evidence only: the captured block's locator and its span on the page (S11d). */
  locator?: Record<string, unknown>
  block?: { block_id: string; start: number; end: number }
  file: string
}

// A source that is an expert revision record (S9a): who changed the field, when, from what to
// what and why. It opens no file.
export interface ExpertCitation {
  kind: 'expert_revision'
  release_id: string
  member: string
  evidence_index: number
  origin: string
  quote: string
  revision_record_id: string
  actor: string
  role: string
  recorded_at: string
  before: { state: string; value: unknown }
  after: { state: string; value: unknown }
  reason: string
}

export function isExpertCitation(citation: Citation | ExpertCitation): citation is ExpertCitation {
  return (citation as ExpertCitation).kind === 'expert_revision'
}

export class EnterpriseError extends Error {
  readonly code: string
  readonly status?: number

  constructor(code: string, status?: number) {
    super(code)
    this.name = 'EnterpriseError'
    this.code = code
    this.status = status
  }
}

const SPACES = '/api/v1/enterprise/spaces'

function releasesPath(spaceId: string): string {
  return `${SPACES}/${encodeURIComponent(spaceId)}/view/releases`
}

async function response<T>(send: () => Promise<unknown>): Promise<T> {
  let body: unknown
  try {
    body = await send()
  } catch (error) {
    const failure = (error ?? {}) as { code?: unknown; status?: unknown }
    const code = typeof failure.code === 'string' && failure.code ? failure.code : 'REQUEST_FAILED'
    throw new EnterpriseError(code, typeof failure.status === 'number' ? failure.status : undefined)
  }
  const envelope = (body ?? {}) as { success?: unknown; data?: unknown; code?: unknown; $httpStatus?: unknown }
  if (typeof body !== 'object' || envelope.success !== true) {
    throw new EnterpriseError(typeof envelope.code === 'string' && envelope.code ? envelope.code : 'INVALID_RESPONSE',
      typeof envelope.$httpStatus === 'number' ? envelope.$httpStatus : undefined)
  }
  return envelope.data as T
}

const read = <T>(url: string) => response<T>(() => get(url))

export async function listSpaces(): Promise<string[]> {
  const data = await read<{ spaces?: { space_id: string }[] }>(SPACES)
  return (data?.spaces ?? []).map(space => space.space_id)
}

const releaseReads = new Map<string, Promise<Release>>()

export function readRelease(spaceId: string, releaseId?: string): Promise<Release> {
  const target = releaseId === undefined ? 'active' : encodeURIComponent(releaseId)
  const url = `${releasesPath(spaceId)}/${target}`
  // A login or tenant change while a request is pending starts a distinct read.
  // Keep only pending work: every later read must revalidate server authorization.
  const session = typeof localStorage === 'undefined' ? [] : [
    localStorage.getItem('weknora_token'), localStorage.getItem('weknora_selected_tenant_id'),
  ]
  const key = JSON.stringify([url, ...session])
  const pending = releaseReads.get(key)
  if (pending) return pending
  const request = read<Release>(url).then(markRaw).finally(() => { releaseReads.delete(key) })
  releaseReads.set(key, request)
  return request
}

export function readCitation(
  spaceId: string, releaseId: string, member: string, evidence: number,
): Promise<Citation | ExpertCitation> {
  const query = new URLSearchParams({ member, evidence: String(evidence) })
  return read<Citation | ExpertCitation>(`${releasesPath(spaceId)}/${encodeURIComponent(releaseId)}/citation?${query}`)
}

export interface ExpertEditInput {
  base_release_id: string
  member_slug: string
  base_member_digest: string
  state: 'present' | 'absent_explicitly' | 'unknown'
  value: string
  reason: string
}

export interface ExpertEditResult {
  release_id: string
  epoch: number
  revision_record_id: string
}

// Saving publishes at once (S9a): the result names the release the edit produced.
export function submitExpertEdit(spaceId: string, input: ExpertEditInput): Promise<ExpertEditResult> {
  const body: ExpertEditInput = {
    base_release_id: input.base_release_id, member_slug: input.member_slug,
    base_member_digest: input.base_member_digest, state: input.state, value: input.value, reason: input.reason,
  }
  return response<ExpertEditResult>(() => post(`${SPACES}/${encodeURIComponent(spaceId)}/view/expert-edits`, body))
}


export interface SpotVerdict {
  id: string
  sample_id: string
  outcome: 'correct' | 'incomplete' | 'wrong'
  note: string
  reviewer: string
  decided_at: string
}

export interface SpotSample {
  id: string
  space_id: string
  release_id: string
  logical_slug: string
  member_digest: string
  stratum: string
  created_by: string
  created_at: string
  verdict?: SpotVerdict
}

export async function listSamples(spaceId: string, status: 'pending' | 'decided'): Promise<SpotSample[]> {
  const query = new URLSearchParams({ status })
  const data = await read<{ samples: SpotSample[] }>(`${SPACES}/${encodeURIComponent(spaceId)}/view/samples?${query}`)
  return data.samples
}

export async function submitVerdict(spaceId: string, sampleId: string, outcome: SpotVerdict['outcome'], note: string): Promise<SpotVerdict> {
  const data = await response<{ verdict: SpotVerdict }>(() => post(
    `${SPACES}/${encodeURIComponent(spaceId)}/view/samples/${encodeURIComponent(sampleId)}/verdicts`, { outcome, note },
  ))
  return data.verdict
}

// Confirmation items (S5b-3a): titles, details and option labels are the submitter's opaque text.
export interface ConfirmationOption { key: string; label: string }

export interface ConfirmationAnswer {
  id: string
  item_id: string
  option_key: string
  note: string
  answerer: string
  answered_at: string
}

export interface ConfirmationClosure {
  reason: 'applied' | 'obsolete'
  answer_id?: string
  closed_by: string
  closed_at: string
}

export interface ConfirmationItem {
  id: string
  space_id: string
  subject: string
  revision: string
  content_digest: string
  title: string
  detail: string
  source_ref?: string
  options: ConfirmationOption[]
  created_by: string
  created_at: string
  answer?: ConfirmationAnswer
  closure?: ConfirmationClosure
}

export async function listConfirmations(spaceId: string, status: 'open' | 'closed'): Promise<ConfirmationItem[]> {
  const query = new URLSearchParams({ status })
  const data = await read<{ items: ConfirmationItem[] }>(`${SPACES}/${encodeURIComponent(spaceId)}/view/confirmations?${query}`)
  return data.items
}

export async function answerConfirmation(spaceId: string, itemId: string, optionKey: string, note: string): Promise<ConfirmationAnswer> {
  const data = await response<{ answer: ConfirmationAnswer }>(() => post(
    `${SPACES}/${encodeURIComponent(spaceId)}/view/confirmations/${encodeURIComponent(itemId)}/answers`,
    { option_key: optionKey, note },
  ))
  return data.answer
}

export async function readConfirmationFile(spaceId: string, itemId: string, signal?: AbortSignal): Promise<Blob> {
  let body: unknown
  try {
    body = await get(`${SPACES}/${encodeURIComponent(spaceId)}/view/confirmations/${encodeURIComponent(itemId)}/file`,
      { responseType: 'blob', signal })
  } catch (error) {
    const failure = (error ?? {}) as { code?: unknown; status?: unknown }
    const code = typeof failure.code === 'string' && failure.code ? failure.code : 'REQUEST_FAILED'
    throw new EnterpriseError(code, typeof failure.status === 'number' ? failure.status : undefined)
  }
  if (!(body instanceof Blob)) throw new EnterpriseError('INVALID_RESPONSE')
  return body
}

// Administrator-only session review routes; no candidate data is cached.
export interface ReviewDecision {
  decision_id: string; outcome: string; mode: string; reason: string; subject: string; created_at: string
}
export interface ReviewItem {
  candidate_id: string; created_at: string; created_by: string; base_release_id: string
  status: 'pending' | 'approved' | 'rejected' | 'released'
  subjects: string[]; members: number; removals: number; point_count: number; pending_points: number
  decision: ReviewDecision | null; release_id: string | null
}
export interface ReviewDetail extends ReviewItem {
  head_release_id: string | null; blocker: string
  bundle_members: ReleaseMember[]; bundle_removals: string[]; points: ReviewPoint[]
}
export interface ReviewPoint {
  slug: string; kind: 'claim' | 'member' | 'removal'; status: ReviewItem['status']
  decision: { outcome: string; reason: string; subject: string; created_at: string } | null
  release_id: string | null; blocker: string
}
export interface PointResult {
  status: ReviewItem['status']
  release_id: string | null; epoch: number | null
  points: { slug: string; status: 'released' | 'rejected' }[]
}
const reviewsPath = (spaceId: string) => `${SPACES}/${encodeURIComponent(spaceId)}/view/candidates`
export async function listReviews(spaceId: string, status: 'pending' | 'decided'): Promise<ReviewItem[]> {
  const data = await read<{ items: ReviewItem[] }>(`${reviewsPath(spaceId)}?${new URLSearchParams({ status })}`)
  return data.items
}
export function readReview(spaceId: string, candidateId: string): Promise<ReviewDetail> {
  return read<ReviewDetail>(`${reviewsPath(spaceId)}/${encodeURIComponent(candidateId)}`)
}
export function decidePoints(spaceId: string, candidateId: string, slugs: string[], outcome: 'approve' | 'reject', reason: string): Promise<PointResult> {
  return response<PointResult>(() => post(`${reviewsPath(spaceId)}/${encodeURIComponent(candidateId)}/points/decisions`, {
    slugs, outcome, reason: trimReviewReason(reason),
  }))
}
