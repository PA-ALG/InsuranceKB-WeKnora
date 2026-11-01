import type { Release } from './enterpriseApi'
import { navigationTree } from './navigationView'
import { entitySummaries, entityTypes, entityView, profileMemberFor, type FieldView } from './releaseView'

export interface FieldChange {
  entityId: string; name: string; fieldKey: string; fieldTitle: string; slug: string
  before: FieldView | null; after: FieldView | null
}
export interface ReleaseChanges {
  added: FieldChange[]; changed: FieldChange[]; removed: FieldChange[]; otherChanged: number
}
type RecordValue = Record<string, unknown>
const text = (value: unknown) => typeof value === 'string' ? value : ''
const records = (value: unknown): RecordValue[] => Array.isArray(value)
  ? value.filter((item): item is RecordValue => !!item && typeof item === 'object' && !Array.isArray(item)) : []

export function previousReleaseId(current: Release): string | undefined {
  const id = current.base_release_id
  if (!id) return undefined
  if (!id.trim() || id === 'active' || id === current.id) throw new Error('INVALID_BASE_RELEASE')
  return id
}

export function orderedEntityIds(release: Release): string[] {
  const grouped = navigationTree(release).flatMap(domain => domain.groups
    .filter(group => group.key !== '__other__').flatMap(group => group.entries.map(entry => entry.entityId)))
  const seen = new Set(grouped)
  return [...grouped, ...entitySummaries(release).filter(entry => !seen.has(entry.entityId)).map(entry => entry.entityId)]
}

function fields(release: Release) {
  const projected = new Map<string, { entityId: string; name: string; fieldKey: string; field: FieldView; digest: string }>()
  const types = entityTypes(release)
  for (const entityId of orderedEntityIds(release)) {
    const view = entityView(release, entityId)
    if (!view) continue
    const rendered = new Map([...view.sections.flatMap(section => section.fields), ...view.other, ...view.generated]
      .map(field => [field.slug, field]))
    const profile = profileMemberFor(release, types.get(entityId) ?? '', view.labels)
    const keys = records(profile?.sections).flatMap(section => records(section.fields)).map(field => text(field.field_key))
    const order = new Map([...new Set(keys)].map((key, index) => [key, index]))
    const claims = release.members.filter(member => member.kind === 'claim' && member.payload?.subject_ref === entityId)
    claims.sort((a, b) => (order.get(text(a.payload.predicate)) ?? order.size) - (order.get(text(b.payload.predicate)) ?? order.size))
    for (const member of claims) {
      const field = rendered.get(member.logical_slug)
      if (field) projected.set(member.logical_slug, { entityId, name: view.name, fieldKey: text(member.payload.predicate), field, digest: member.member_digest })
    }
  }
  return projected
}

export function releaseChanges(current: Release, base: Release | null): ReleaseChanges | null {
  if (!base) return null
  const now = fields(current), before = fields(base)
  const result: ReleaseChanges = { added: [], changed: [], removed: [], otherChanged: 0 }
  for (const [slug, entry] of now) {
    const previous = before.get(slug)
    if (previous?.digest === entry.digest) continue
    const row = { entityId: entry.entityId, name: entry.name, slug, fieldKey: entry.fieldKey,
      fieldTitle: entry.field.title || entry.fieldKey, before: previous?.field ?? null, after: entry.field }
    ;(previous ? result.changed : result.added).push(row)
  }
  for (const [slug, entry] of before) {
    if (!now.has(slug)) result.removed.push({ entityId: entry.entityId, name: entry.name, slug, fieldKey: entry.fieldKey,
      fieldTitle: entry.field.title || entry.fieldKey, before: entry.field, after: null })
  }
  const others = (release: Release) => new Map(release.members.filter(member => member.kind !== 'claim')
    .map(member => [member.logical_slug, member.member_digest]))
  const oldOthers = others(base), newOthers = others(current)
  for (const slug of new Set([...oldOthers.keys(), ...newOthers.keys()])) {
    if (!oldOthers.has(slug) || !newOthers.has(slug) || oldOthers.get(slug) !== newOthers.get(slug)) result.otherChanged++
  }
  return result
}
