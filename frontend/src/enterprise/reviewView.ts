import type { Release, ReviewDetail } from './enterpriseApi'
import { entitySummaries, entityView, type FieldView } from './releaseView'
import { entityReview, type EntityReview } from './entityReview'

export interface ReviewRow {
  slug: string; title: string; beforeExists: boolean; before: FieldView | null; after: FieldView | null; quotes: string[]
  entity?: EntityReview
}

function fields(release: Release) {
  const rows = new Map<string, { title: string; field: FieldView }>()
  for (const entity of entitySummaries(release)) {
    const view = entityView(release, entity.entityId)!
    for (const field of [...view.sections.flatMap(section => section.fields), ...view.other, ...view.generated]) {
      // Candidate evidence is plain text, never a link into an unpublished release.
      rows.set(field.slug, { title: `${entity.name} · ${field.title}`, field: { ...field, evidenceCount: 0 } })
    }
  }
  return rows
}

export function reviewRows(detail: ReviewDetail, release: Release | null): Map<string, ReviewRow> {
  const base: Release = release ?? { id: '', epoch: 0, members: [] }
  const comparable = detail.head_release_id === (release?.id ?? null)
  const existing = new Set(base.members.map(member => member.logical_slug))
  const before = comparable ? fields(base) : new Map<string, { title: string; field: FieldView }>()
  const members = new Map(base.members.map(member => [member.logical_slug, member]))
  const proposed = new Map(detail.bundle_members.map(member => [member.logical_slug, member]))
  for (const member of detail.bundle_members) members.set(member.logical_slug, member)
  for (const slug of detail.bundle_removals) members.delete(slug)
  const afterRelease = { ...base, members: [...members.values()] }
  const entityAfterRelease = comparable ? afterRelease : { ...base, members: detail.bundle_members }
  const after = fields(afterRelease)
  return new Map(detail.points.map(point => {
    const old = before.get(point.slug), next = after.get(point.slug)
    const evidence = proposed.get(point.slug)?.payload?.evidence
    const claim = point.kind === 'claim'
    const entity = claim ? undefined : entityReview(point.slug,
      comparable ? base.members.find(member => member.logical_slug === point.slug) : undefined,
      proposed.get(point.slug), comparable, comparable ? base : { ...base, members: [] }, entityAfterRelease)
    return [point.slug, {
      slug: point.slug, title: entity?.name ?? (point.kind === 'member' ? point.slug : next?.title || old?.title || point.slug),
      ...(entity ? { entity } : {}),
      beforeExists: comparable && existing.has(point.slug),
      before: point.kind === 'member' ? null : old?.field ?? null,
      after: claim ? next?.field ?? null : null,
      quotes: claim && Array.isArray(evidence) ? evidence.flatMap(value =>
        value && typeof value === 'object' && typeof value.quote === 'string' ? [value.quote] : []) : [],
    }]
  }))
}
