import { get, post } from '@/utils/request'

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
  members: ReleaseMember[]
}

export interface Citation {
  release_id: string
  member: string
  evidence_index: number
  origin: string
  source: { knowledge_id: string; parse_attempt: number; document: string; file_sha256: string }
  page: { number: number; width_points: string; height_points: string }
  start: number
  end: number
  quote: string
  highlight: { coordinate_space: string; complete: boolean; rects: [number, number, number, number][] }
  file: string
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
  const envelope = (body ?? {}) as { success?: unknown; data?: unknown; code?: unknown }
  if (typeof body !== 'object' || envelope.success !== true) {
    throw new EnterpriseError(typeof envelope.code === 'string' && envelope.code ? envelope.code : 'INVALID_RESPONSE')
  }
  return envelope.data as T
}

const read = <T>(url: string) => response<T>(() => get(url))

export async function listSpaces(): Promise<string[]> {
  const data = await read<{ spaces?: { space_id: string }[] }>(SPACES)
  return (data?.spaces ?? []).map(space => space.space_id)
}

export function readRelease(spaceId: string, releaseId?: string): Promise<Release> {
  const target = releaseId === undefined ? 'active' : encodeURIComponent(releaseId)
  return read<Release>(`${releasesPath(spaceId)}/${target}`)
}

export function readCitation(spaceId: string, releaseId: string, member: string, evidence: number): Promise<Citation> {
  const query = new URLSearchParams({ member, evidence: String(evidence) })
  return read<Citation>(`${releasesPath(spaceId)}/${encodeURIComponent(releaseId)}/citation?${query}`)
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
