// RV6c acceptance fixtures (protected, written by Claude): a pending candidate on the s3e release
// rel-9 with one review point of each kind the page must show (Spec
// docs/design/slices/RV6c-逐字段审核页面与首页工作台.md §1; point shape per RV6b Spec §5.2):
//   M1/waiting_period       claim, changed 90日 → 180日
//   M2/waiting_period       claim, filled unknown → 30日
//   M1/cooling_off_period   claim, candidate value unknown (unknown group)
//   M2/premium_grace_period claim, candidate value unknown (unknown group)
//   M2/cooling_off_period   claim, changed, blocked by NEEDS_REBASE
//   M1/premium_grace_period removal of 60日
//   entity/M1               non-claim member changed
import type { PointResult, ReleaseMember, ReviewDetail, ReviewItem, ReviewPoint } from '../enterpriseApi'
import { claim, member } from './s3eFixtures'

export const PENDING_SLUGS = [
  'M1/cooling_off_period', 'M1/premium_grace_period', 'M1/waiting_period',
  'M2/cooling_off_period', 'M2/premium_grace_period', 'M2/waiting_period', 'entity/M1',
]
export const UNKNOWN_SLUGS = ['M1/cooling_off_period', 'M2/premium_grace_period']
export const CARD_SLUGS = ['M1/premium_grace_period', 'M1/waiting_period', 'M2/cooling_off_period', 'M2/waiting_period', 'entity/M1']

function quoted(value: ReleaseMember, quote: string): ReleaseMember {
  return { ...value, payload: { ...value.payload, evidence: [{ quote }] } }
}

export function pointItem(id = 'cand-1', extra: Partial<ReviewItem> = {}): ReviewItem {
  return {
    candidate_id: id, created_at: '2026-10-27T08:00:00Z', created_by: 'svc-harness', base_release_id: 'rel-9',
    status: 'pending', subjects: ['M1', 'M2'], members: 6, removals: 1, decision: null, release_id: null,
    point_count: 7, pending_points: 7, ...extra,
  }
}

const KINDS: Record<string, ReviewPoint['kind']> = { 'M1/premium_grace_period': 'removal', 'entity/M1': 'member' }

export function point(slug: string, extra: Partial<ReviewPoint> = {}): ReviewPoint {
  return {
    slug, kind: KINDS[slug] ?? 'claim', status: 'pending', decision: null, release_id: null,
    blocker: slug === 'M2/cooling_off_period' ? 'NEEDS_REBASE' : '', ...extra,
  }
}

export function released(slug: string, reason = '核对无误', releaseId = 'rel-10'): ReviewPoint {
  return point(slug, {
    status: 'released', release_id: releaseId, blocker: '',
    decision: { outcome: 'approve', reason, subject: 'user:u-1', created_at: '2026-10-27T09:00:00Z' },
  })
}

export function rejected(slug: string, reason = '取值与条款不符'): ReviewPoint {
  return point(slug, {
    status: 'rejected', blocker: '',
    decision: { outcome: 'reject', reason, subject: 'user:u-1', created_at: '2026-10-27T09:00:00Z' },
  })
}

export function pointDetail(id = 'cand-1', points: ReviewPoint[] = PENDING_SLUGS.map(slug => point(slug)),
  extra: Partial<ReviewDetail> = {}): ReviewDetail {
  const pending = points.filter(entry => entry.status === 'pending').length
  return {
    ...pointItem(id, { pending_points: pending, point_count: points.length }), head_release_id: 'rel-9', blocker: '',
    bundle_members: [
      claim('M1', 'cooling_off_period', 'unknown', null, 0, '2'.repeat(64)),
      quoted(claim('M1', 'waiting_period', 'present', '180日。', 1, 'f'.repeat(64)), '等待期为180日。'),
      quoted(claim('M2', 'cooling_off_period', 'present', '自签收之日起20日。', 1, '3'.repeat(64)), '犹豫期为20日。'),
      claim('M2', 'premium_grace_period', 'unknown', null, 0, '4'.repeat(64)),
      quoted(claim('M2', 'waiting_period', 'present', '30日。', 1, '1'.repeat(64)), '本合同的等待期为30日。'),
      member('entity', 'entity/M1', {
        entity_id: 'M1', entity_type: 'insurance_product', names: ['甲医疗', '甲医疗保险'], classification_labels: ['medical'],
      }, '5'.repeat(64)),
    ],
    bundle_removals: ['M1/premium_grace_period'],
    points,
    ...extra,
  }
}

export function pointResult(slugs: string[], status: 'released' | 'rejected', extra: Partial<PointResult> = {}): PointResult {
  return {
    status: 'pending', release_id: status === 'released' ? 'rel-10' : null, epoch: status === 'released' ? 16 : null,
    points: slugs.map(slug => ({ slug, status })), ...extra,
  }
}
