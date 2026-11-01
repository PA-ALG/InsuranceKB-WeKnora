import type { Release, ReleaseMember } from './enterpriseApi'
import type { EntitySummary } from './releaseView'

// A product version's published sale period (PV-4a); dates are YYYY-MM-DD and source_status is
// a snapshot taken at basis_date. Only the keys a release states are present.
export interface Lifecycle {
  sale_start?: string
  sale_end?: string
  source_status?: string
  basis_commit?: string
  basis_date?: string
}
export type SaleStatus = 'on_sale' | 'discontinued' | 'not_yet_on_sale' | 'unknown'
export interface VersionFamily { key: string; title: string }
export interface VersionLink { entityId: string; name: string; lifecycle: Lifecycle | null }
export interface VersionInfo {
  lifecycle: Lifecycle | null
  // null for an entity without a lifecycle: it shows no status at all
  status: SaleStatus | null
  family: VersionFamily | null
  predecessors: VersionLink[]
  successors: VersionLink[]
}
export interface FamilyCluster { family: VersionFamily | null; entries: EntitySummary[] }

// Asia/Shanghai as the fixed offset the platform uses (PV-4b Spec §1.1), whatever the browser's zone.
const BUSINESS_OFFSET_MS = 8 * 60 * 60 * 1000
const LIFECYCLE_KEYS = ['sale_start', 'sale_end', 'source_status', 'basis_commit', 'basis_date'] as const

export function businessDay(instant: Date): string {
  return new Date(instant.getTime() + BUSINESS_OFFSET_MS).toISOString().slice(0, 10)
}

// The platform's rule (Spec §1.2), checked against the same vectors: dates known to have passed
// win over the source snapshot, and an unknown end alone never means a version is on sale.
export function saleStatus(lifecycle: Lifecycle | null, day: string): SaleStatus {
  if (!lifecycle) return 'unknown'
  const { sale_start: start, sale_end: end, source_status: source } = lifecycle
  if (start && day < start) return 'not_yet_on_sale'
  if (end && day >= end) return 'discontinued'
  if (!start) return 'unknown'
  if (end ? source !== 'discontinued' : source === 'on_sale') return 'on_sale'
  return 'unknown'
}

type RecordValue = Record<string, unknown>
const record = (value: unknown): RecordValue | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as RecordValue : null
const text = (value: unknown): string => typeof value === 'string' ? value : ''

function lifecycleOf(payload: RecordValue): Lifecycle | null {
  const value = record(payload.lifecycle)
  if (!value) return null
  const out: Lifecycle = {}
  for (const key of LIFECYCLE_KEYS) if (text(value[key])) out[key] = text(value[key])
  return out
}

function familyOf(payload: RecordValue): VersionFamily | null {
  const value = record(payload.product_family)
  const key = text(value?.key).trim()
  return value && key ? { key, title: text(value.display_name).trim() || key } : null
}

// The first entity member of each ID, as the entry list reads them.
function entityPayloads(release: Release): Map<string, RecordValue> {
  const out = new Map<string, RecordValue>()
  for (const member of release.members) {
    const payload = member.kind === 'entity' ? record(member.payload) : null
    const id = text(payload?.entity_id)
    if (payload && id && !out.has(id)) out.set(id, payload)
  }
  return out
}

function nameOf(payload: RecordValue, entityId: string): string {
  const names = Array.isArray(payload.names) ? payload.names : []
  return text(names[0]) || entityId
}

function isSupersedes(member: ReleaseMember): RecordValue | null {
  const payload = member.kind === 'relation' ? record(member.payload) : null
  return payload?.predicate === 'supersedes' && text(payload.from) && text(payload.to) ? payload : null
}

// Status, family and supersedes links of one entity in this release. A link is kept only when both
// of its ends are entities of the release, as the platform reads it.
export function versionInfo(release: Release, entityId: string, day: string): VersionInfo {
  const payloads = entityPayloads(release)
  const payload = payloads.get(entityId)
  const lifecycle = payload ? lifecycleOf(payload) : null
  const links = (self: 'from' | 'to', other: 'from' | 'to') => {
    const out: VersionLink[] = []
    if (!payload) return out
    for (const member of release.members) {
      const relation = isSupersedes(member)
      const id = text(relation?.[other])
      const end = payloads.get(id)
      if (!relation || text(relation[self]) !== entityId || id === entityId || !end) continue
      if (!out.some(link => link.entityId === id)) out.push({ entityId: id, name: nameOf(end, id), lifecycle: lifecycleOf(end) })
    }
    return out
  }
  return {
    lifecycle,
    status: lifecycle ? saleStatus(lifecycle, day) : null,
    family: payload ? familyOf(payload) : null,
    predecessors: links('from', 'to'),
    successors: links('to', 'from'),
  }
}

// Sale status of every entity with a lifecycle; the others have none.
export function saleStatuses(release: Release, day: string): Map<string, SaleStatus> {
  const out = new Map<string, SaleStatus>()
  for (const [id, payload] of entityPayloads(release)) {
    const lifecycle = lifecycleOf(payload)
    if (lifecycle) out.set(id, saleStatus(lifecycle, day))
  }
  return out
}

export function visibleEntries(
  release: Release, entries: EntitySummary[], day: string, options: { includeDiscontinued: boolean; keep?: string },
): EntitySummary[] {
  if (options.includeDiscontinued) return entries
  const statuses = saleStatuses(release, day)
  return entries.filter(entry => entry.entityId === options.keep || statuses.get(entry.entityId) !== 'discontinued')
}

export function discontinuedCount(release: Release, entries: EntitySummary[], day: string): number {
  const statuses = saleStatuses(release, day)
  return entries.filter(entry => statuses.get(entry.entityId) === 'discontinued').length
}

// Entries of one family that has two or more of them form a cluster at the place of its first
// entry, newest sale start first (unknown last); runs of the other entries keep their order.
export function familyClusters(release: Release, entries: EntitySummary[]): FamilyCluster[] {
  const payloads = entityPayloads(release)
  const families = new Map<string, VersionFamily>()
  const members = new Map<string, EntitySummary[]>()
  for (const entry of entries) {
    const payload = payloads.get(entry.entityId)
    const family = payload ? familyOf(payload) : null
    if (!family) continue
    if (!families.has(family.key)) families.set(family.key, family)
    members.set(family.key, [...(members.get(family.key) ?? []), entry])
  }
  const start = (entry: EntitySummary) => {
    const payload = payloads.get(entry.entityId)
    return (payload && lifecycleOf(payload)?.sale_start) || ''
  }
  const out: FamilyCluster[] = []
  const placed = new Set<string>()
  for (const entry of entries) {
    const payload = payloads.get(entry.entityId)
    const key = payload ? familyOf(payload)?.key : undefined
    const cluster = key ? members.get(key)! : []
    if (key && cluster.length >= 2) {
      if (placed.has(key)) continue
      placed.add(key)
      // Array.prototype.sort is stable: equal starts keep their order, unknown ('') sorts last.
      const newestFirst = (a: EntitySummary, b: EntitySummary) => start(a) > start(b) ? -1 : start(a) < start(b) ? 1 : 0
      out.push({ family: families.get(key)!, entries: [...cluster].sort(newestFirst) })
      continue
    }
    const last = out[out.length - 1]
    if (last && !last.family) last.entries.push(entry)
    else out.push({ family: null, entries: [entry] })
  }
  return out
}
