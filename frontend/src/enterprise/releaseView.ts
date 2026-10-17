import type { Release, ReleaseMember } from './enterpriseApi'

// A release as entity summaries and entity pages, by the reader rules of S3d-2 Spec §3.1:
// the platform stores members generically, so grouping and titles come from the published
// presentation profile, never from field keys known to this code.

export interface EntitySummary {
  entityId: string
  name: string
  labels: string[]
  fieldCount: number
}

export interface FieldView {
  slug: string
  title: string
  state: string
  value: string | string[] | null
  origin: string
  evidenceCount: number
}

export interface SectionView {
  key: string
  title: string
  fields: FieldView[]
}

export interface EntityView {
  entityId: string
  name: string
  labels: string[]
  sections: SectionView[]
  other: FieldView[]
  // Model-generated content stays apart from sourced content (hard boundary 6).
  generated: FieldView[]
}

const MODEL_GENERATED = 'MODEL_GENERATED'

type Payload = Record<string, unknown>

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function membersOf(release: Release, kind: string): Payload[] {
  return release.members.filter((member: ReleaseMember) => member.kind === kind).map(member => member.payload ?? {})
}

function claimsBySubject(release: Release): Map<string, ReleaseMember[]> {
  const subjects = new Map<string, ReleaseMember[]>()
  for (const member of release.members) {
    if (member.kind !== 'claim') continue
    const subject = text(member.payload?.subject_ref)
    if (!subject) continue
    subjects.set(subject, [...(subjects.get(subject) ?? []), member])
  }
  return subjects
}

function identity(entity: Payload): { entityId: string; name: string; labels: string[] } {
  const entityId = text(entity.entity_id)
  return { entityId, name: strings(entity.names)[0] || entityId, labels: strings(entity.classification_labels) }
}

export function entitySummaries(release: Release): EntitySummary[] {
  const subjects = claimsBySubject(release)
  const summaries: EntitySummary[] = []
  const seen = new Set<string>()
  for (const entity of membersOf(release, 'entity')) {
    const { entityId, name, labels } = identity(entity)
    if (!entityId || seen.has(entityId)) continue
    seen.add(entityId)
    summaries.push({ entityId, name, labels, fieldCount: subjects.get(entityId)?.length ?? 0 })
  }
  for (const [subject, claims] of subjects) {
    if (seen.has(subject)) continue
    summaries.push({ entityId: subject, name: subject, labels: [], fieldCount: claims.length })
  }
  return summaries
}

function formatValue(state: string, value: unknown): string | string[] | null {
  if (state !== 'present' || value === null || value === undefined) return null
  if (Array.isArray(value)) return value.map(item => String(item))
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function fieldView(member: ReleaseMember, title: string): FieldView {
  const payload = member.payload ?? {}
  const state = text(payload.state)
  return {
    slug: member.logical_slug,
    title,
    state,
    value: formatValue(state, payload.value),
    origin: text(payload.origin),
    evidenceCount: Array.isArray(payload.evidence) ? payload.evidence.length : 0,
  }
}

interface ProfileSection { key: string; title: string; fields: { key: string; title: string }[] }

function profileFor(release: Release, labels: string[]): ProfileSection[] {
  const profile = membersOf(release, 'presentation_profile')
    .find(candidate => strings(candidate.classification_labels).some(label => labels.includes(label)))
  const sections = Array.isArray(profile?.sections) ? (profile!.sections as Payload[]) : []
  return sections.map(section => ({
    key: text(section.section_key),
    title: text(section.display_name),
    fields: (Array.isArray(section.fields) ? (section.fields as Payload[]) : [])
      .map(field => ({ key: text(field.field_key), title: text(field.short_title) })),
  }))
}

function byPredicate(left: [string, ReleaseMember], right: [string, ReleaseMember]): number {
  return left[0] < right[0] ? -1 : left[0] > right[0] ? 1 : 0
}

export function entityView(release: Release, entityId: string): EntityView | null {
  const entity = membersOf(release, 'entity').find(candidate => text(candidate.entity_id) === entityId)
  const claims = claimsBySubject(release).get(entityId) ?? []
  if (!entity && claims.length === 0) return null
  const { name, labels } = entity ? identity(entity) : { name: entityId, labels: [] as string[] }

  const profile = profileFor(release, labels)
  const titles = new Map(profile.flatMap(section => section.fields.map(field => [field.key, field.title] as const)))
  const sourced = new Map<string, ReleaseMember>()
  const generated: [string, ReleaseMember][] = []
  for (const claim of claims) {
    const predicate = text(claim.payload?.predicate)
    if (text(claim.payload?.origin) === MODEL_GENERATED) generated.push([predicate, claim])
    else sourced.set(predicate, claim)
  }

  const sections: SectionView[] = []
  for (const section of profile) {
    const fields = section.fields.flatMap(field => {
      const claim = sourced.get(field.key)
      if (!claim) return []
      sourced.delete(field.key)
      return [fieldView(claim, field.title)]
    })
    if (fields.length) sections.push({ key: section.key, title: section.title, fields })
  }
  const other = [...sourced.entries()].sort(byPredicate).map(([predicate, claim]) => fieldView(claim, predicate))
  const apart = generated.sort(byPredicate)
    .map(([predicate, claim]) => fieldView(claim, titles.get(predicate) || predicate))
  return { entityId, name, labels, sections, other, generated: apart }
}
