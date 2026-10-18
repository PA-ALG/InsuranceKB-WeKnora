import type { Release, SpotSample } from './enterpriseApi'
import { entityView } from './releaseView'

// Locate by immutable member identity; never substitute another predicate or a newer release.
export function sampledField(sample: SpotSample, release?: Release) {
  if (!release || release.id !== sample.release_id) return null
  const members = release.members.filter(member => member.logical_slug === sample.logical_slug)
  const member = members[0]
  if (members.length !== 1 || member?.kind !== 'claim' || member.access_scope !== 'space'
    || !sample.member_digest || member.member_digest !== sample.member_digest) return null
  const subject = member.payload?.subject_ref
  if (typeof subject !== 'string' || !subject) return null
  const entity = entityView(release, subject)
  if (!entity) return null
  const field = [...entity.sections.flatMap(section => section.fields), ...entity.other, ...entity.generated]
    .find(field => field.slug === sample.logical_slug)
  return field ? { entityId: entity.entityId, name: entity.name, field } : null
}
