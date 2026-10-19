// S3h-2 acceptance fixtures (protected, written by Claude): a current release built on a base
// release, with one claim added, two changed, one removed and one non-claim member changed.
import type { Release } from '../enterpriseApi'
import { claim, release } from './s3eFixtures'

export function baseRelease(): Release {
  return { ...release(), id: 'rel-8', epoch: 14 }
}

export function currentRelease(): Release & { base_release_id: string } {
  const data = release({ changedDigest: true }) // C1/cooling_off_period: digest changed
  const members = data.members
    .filter(member => member.logical_slug !== 'M1/premium_grace_period') // removed
    .map(member => member.logical_slug === 'M1/waiting_period' // changed value
      ? claim('M1', 'waiting_period', 'present', '180日。', 1, 'f'.repeat(64))
      : member.kind === 'navigation' ? { ...member, member_digest: '9'.repeat(64) } : member)
  members.push(claim('C1', 'waiting_period', 'present', '180日。', 1, '7'.repeat(64))) // added
  return { ...data, members, base_release_id: 'rel-8' }
}

// Only a non-claim member differs from the base.
export function navigationOnlyRelease(): Release & { base_release_id: string } {
  const data = release()
  const members = data.members.map(member => member.kind === 'navigation' ? { ...member, member_digest: '9'.repeat(64) } : member)
  return { ...data, members, base_release_id: 'rel-8' }
}
