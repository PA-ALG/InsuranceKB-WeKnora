// PV-4b acceptance fixtures (protected, written by Claude): a release whose product entities carry
// PV-4a version data. V1 and V2 are two filings of one name in family 甲护理 (V2 supersedes V1, V1
// is discontinued); B1 is a second member of the family that starts later; U1 has no version data;
// GHOST is not in the release. Synthetic data only (Spec docs/design/slices/PV-4b-读取侧.md §3).
import type { Release, ReleaseMember } from '../enterpriseApi'
import { claim, member } from './s3eFixtures'

export const VERSION_NOW = new Date('2026-11-01T02:00:00Z') // 2026-11-01 in the business time zone

const NAVIGATION = member('navigation', 'navigation/enterprise', {
  navigation_id: 'enterprise',
  navigation_version: 'v1',
  domains: [{
    domain_key: 'product', display_name: '产品库', entity_types: ['insurance_product'],
    groups: [
      { group_key: 'pack_nursing', display_name: '护理险', classification_labels: ['nursing'] },
      { group_key: 'pack_medical', display_name: '医疗险', classification_labels: ['medical'] },
    ],
  }],
})

function product(id: string, label: string, names: string[], extra: Record<string, unknown> = {}): ReleaseMember {
  return member('entity', `entity/${id}`, {
    entity_id: id, entity_type: 'insurance_product', names, classification_labels: [label], ...extra,
  })
}

function supersedes(newer: string, older: string): ReleaseMember {
  const id = `supersedes/${newer}/${older}`
  return member('relation', `relation/${id}`, { relation_id: id, predicate: 'supersedes', from: newer, to: older })
}

const FAMILY = { product_family: { key: '甲护理', display_name: '甲护理系列' } }

export function versionRelease(): Release {
  return {
    id: 'rel-v', epoch: 9, members: [
      NAVIGATION,
      product('V1', 'nursing', ['甲护理保险'], {
        ...FAMILY, lifecycle: { sale_start: '2023-01-01', sale_end: '2024-04-23', source_status: 'discontinued' },
      }),
      product('V2', 'nursing', ['甲护理保险'], {
        ...FAMILY, lifecycle: { sale_start: '2024-04-23', source_status: 'on_sale', basis_date: '2026-10-20' },
      }),
      product('B1', 'nursing', ['甲护理保险（尊享版）'], {
        ...FAMILY, lifecycle: { sale_start: '2027-01-01', source_status: 'on_sale' },
      }),
      product('U1', 'medical', ['丙医疗保险']),
      supersedes('V2', 'V1'),
      supersedes('V2', 'GHOST'),
      claim('V1', 'waiting_period', 'present', '90日'),
      claim('V2', 'waiting_period', 'present', '90日'),
      claim('B1', 'waiting_period', 'present', '60日'),
      claim('U1', 'waiting_period', 'present', '30日'),
    ],
  }
}
