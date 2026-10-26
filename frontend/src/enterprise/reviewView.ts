import type { Release, ReviewDetail } from './enterpriseApi'
import { releaseChanges } from './releaseChanges'
import type { FieldView } from './releaseView'

export function reviewChanges(detail: ReviewDetail, release: Release | null) {
  // The detail's head and the loaded snapshot must describe the same comparison. A failed
  // release read is not an empty release; only a server-confirmed null head means no history.
  if (detail.head_release_id !== (release?.id ?? null)) return null
  const base: Release = release ?? { id: '', epoch: 0, members: [] }
  const members = new Map(base.members.map(member => [member.logical_slug, member]))
  for (const member of detail.bundle_members) members.set(member.logical_slug, member)
  for (const slug of detail.bundle_removals) members.delete(slug)
  const changes = releaseChanges({ ...base, members: [...members.values()] }, base)!
  return [...changes.added, ...changes.changed, ...changes.removed].map(row => {
    const member = detail.bundle_members.find(member => member.logical_slug === row.slug)
    const evidence = member?.payload.evidence
    const quotes = Array.isArray(evidence) ? evidence.flatMap(value =>
      value && typeof value === 'object' && typeof value.quote === 'string' ? [value.quote] : []) : []
    // Reuse the published field layout, with no source action for unpublished evidence.
    const plain = (field: FieldView | null) => field ? { ...field, evidenceCount: 0 } : null
    return { ...row, before: plain(row.before), after: plain(row.after), quotes }
  })
}
