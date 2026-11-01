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
  profileName: string
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

/** Each entity's type, by entity ID (first entity member wins, as in the summaries). */
export function entityTypes(release: Release): Map<string, string> {
  const types = new Map<string, string>()
  for (const entity of membersOf(release, 'entity')) {
    const id = text(entity.entity_id)
    if (id && !types.has(id)) types.set(id, text(entity.entity_type))
  }
  return types
}

/**
 * The profile an entity is shown with (SK-3 Spec §1): the first whose entity_types name its type,
 * otherwise the first without entity_types whose classification labels meet the entity's.
 */
export function profileMemberFor(release: Release, type: string, labels: string[]): Payload | undefined {
  const profiles = membersOf(release, 'presentation_profile')
  return (type ? profiles.find(candidate => strings(candidate.entity_types).includes(type)) : undefined)
    ?? profiles.find(candidate => !strings(candidate.entity_types).length
      && strings(candidate.classification_labels).some(label => labels.includes(label)))
}

function profileFor(release: Release, type: string, labels: string[]): { name: string; sections: ProfileSection[] } {
  const profile = profileMemberFor(release, type, labels)
  const sections = Array.isArray(profile?.sections) ? (profile!.sections as Payload[]) : []
  return {
    name: text(profile?.display_name),
    sections: sections.map(section => ({
      key: text(section.section_key),
      title: text(section.display_name),
      fields: (Array.isArray(section.fields) ? (section.fields as Payload[]) : [])
        .map(field => ({ key: text(field.field_key), title: text(field.short_title) })),
    })),
  }
}

// Claims are ordered by predicate, then slug: a predicate is not unique (applicability and
// product version are part of a claim's identity), so every claim of a predicate is kept.
function compare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0
}

function byPredicateThenSlug(left: [string, ReleaseMember], right: [string, ReleaseMember]): number {
  return compare(left[0], right[0]) || compare(left[1].logical_slug, right[1].logical_slug)
}

export function entityView(release: Release, entityId: string): EntityView | null {
  const entity = membersOf(release, 'entity').find(candidate => text(candidate.entity_id) === entityId)
  const claims = claimsBySubject(release).get(entityId) ?? []
  if (!entity && claims.length === 0) return null
  const { name, labels } = entity ? identity(entity) : { name: entityId, labels: [] as string[] }

  const profile = profileFor(release, entity ? text(entity.entity_type) : '', labels)
  const titles = new Map(profile.sections.flatMap(section => section.fields.map(field => [field.key, field.title] as const)))
  const sourced = new Map<string, [string, ReleaseMember][]>()
  const generated: [string, ReleaseMember][] = []
  for (const claim of claims) {
    const predicate = text(claim.payload?.predicate)
    if (text(claim.payload?.origin) === MODEL_GENERATED) generated.push([predicate, claim])
    else sourced.set(predicate, [...(sourced.get(predicate) ?? []), [predicate, claim]])
  }

  const sections: SectionView[] = []
  for (const section of profile.sections) {
    const fields = section.fields.flatMap(field => {
      const matching = sourced.get(field.key)
      if (!matching) return []
      sourced.delete(field.key)
      return matching.sort(byPredicateThenSlug).map(([, claim]) => fieldView(claim, field.title))
    })
    if (fields.length) sections.push({ key: section.key, title: section.title, fields })
  }
  const other = [...sourced.values()].flat().sort(byPredicateThenSlug)
    .map(([predicate, claim]) => fieldView(claim, predicate))
  const apart = generated.sort(byPredicateThenSlug)
    .map(([predicate, claim]) => fieldView(claim, titles.get(predicate) || predicate))
  return { entityId, name, profileName: profile.name, labels, sections, other, generated: apart }
}
