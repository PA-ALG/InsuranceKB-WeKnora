// RV5b acceptance fixtures (protected, written by Claude): a pending candidate that changes one
// field (M1 等待期 90日 → 180日), fills one unknown field (M2 等待期 → 30日) and removes one
// (M1 宽限期), against the s3e release rel-9; plus one decided candidate of each status.
// RV6c: items carry their point counts and the detail its three review points (RV6b §5.2); the
// whole-candidate decision result is gone with the whole-candidate decision.
import type { ReleaseMember, ReviewDetail, ReviewItem } from '../enterpriseApi'
import { claim } from './s3eFixtures'

export function reviewItem(id = 'cand-1', extra: Partial<ReviewItem> = {}): ReviewItem {
  return {
    candidate_id: id, created_at: '2026-10-26T08:00:00Z', created_by: 'svc-harness', base_release_id: 'rel-9',
    status: 'pending', subjects: ['M1', 'M2'], members: 2, removals: 1, decision: null, release_id: null,
    point_count: 3, pending_points: 3, ...extra,
  }
}

function quoted(member: ReleaseMember, quote: string): ReleaseMember {
  return { ...member, payload: { ...member.payload, evidence: [{ quote }] } }
}

export function reviewDetail(id = 'cand-1', extra: Partial<ReviewDetail> = {}): ReviewDetail {
  return {
    ...reviewItem(id), head_release_id: 'rel-9', blocker: '',
    bundle_members: [
      quoted(claim('M1', 'waiting_period', 'present', '180日。', 1, 'f'.repeat(64)), '等待期为180日。'),
      quoted(claim('M2', 'waiting_period', 'present', '30日。', 1, '1'.repeat(64)), '本合同的等待期为30日。'),
    ],
    bundle_removals: ['M1/premium_grace_period'],
    points: [
      { slug: 'M1/premium_grace_period', kind: 'removal', status: 'pending', decision: null, release_id: null, blocker: '' },
      { slug: 'M1/waiting_period', kind: 'claim', status: 'pending', decision: null, release_id: null, blocker: '' },
      { slug: 'M2/waiting_period', kind: 'claim', status: 'pending', decision: null, release_id: null, blocker: '' },
    ],
    ...extra,
  }
}

function decided(id: string, status: ReviewItem['status'], outcome: string, reason: string): ReviewItem {
  return reviewItem(id, {
    status, subjects: ['C1'], members: 1, removals: 0, release_id: status === 'released' ? 'rel-10' : null,
    point_count: 1, pending_points: 0,
    decision: { decision_id: `dec_${id}`, outcome, mode: 'human', reason, subject: 'user:u-1', created_at: '2026-10-26T09:00:00Z' },
  })
}

export function decidedItems(): ReviewItem[] {
  return [
    decided('cand-r', 'released', 'approve', '核对无误'),
    decided('cand-a', 'approved', 'approve', '先批准'),
    decided('cand-x', 'rejected', 'reject', '取值与条款不符'),
  ]
}
