// S3e acceptance fixtures (protected, written by Claude): a release with a navigation member, two
// packs' presentation profiles, five products in three packs and one concept member. Synthetic
// data only; shapes follow docs/design/slices/S3e-企业知识导航与概念页.md §2–§4.
import type { Release, ReleaseMember } from '../enterpriseApi'

export function member(kind: string, slug: string, payload: Record<string, unknown>, digest = 'd'.repeat(64)): ReleaseMember {
  return { kind, logical_slug: slug, payload, member_digest: digest, access_scope: 'space' }
}

export function claim(subject: string, predicate: string, state: string, value: unknown, evidence = 1, digest?: string): ReleaseMember {
  return member('claim', `${subject}/${predicate}`, {
    subject_ref: subject, predicate, state, value, origin: 'SOURCE_SUPPORTED',
    evidence: Array.from({ length: evidence }, (_, index) => ({ quote: `q${index}` })),
  }, digest)
}

export const NAVIGATION = member('navigation', 'navigation/enterprise', {
  navigation_id: 'enterprise',
  navigation_version: 'v1',
  domains: [
    {
      domain_key: 'product', display_name: '产品库', entity_types: ['insurance_product'],
      groups: [
        { group_key: 'pack_medical', display_name: '医疗险', classification_labels: ['medical'] },
        { group_key: 'pack_critical', display_name: '重疾险', classification_labels: ['critical'] },
        { group_key: 'pack_term_life', display_name: '定期寿险', classification_labels: ['term_life'] },
      ],
    },
    {
      domain_key: 'service_benefit', display_name: '服务权益', entity_types: ['service_benefit'],
      groups: [{ group_key: 'family_doctor', display_name: '家庭医生', classification_labels: ['family_doctor'] }],
    },
  ],
})

function profile(id: string, displayName: string, label: string): ReleaseMember {
  return member('presentation_profile', `presentation/${id}`, {
    profile_id: id, display_name: displayName, classification_labels: [label],
    sections: [{
      section_key: 'contract', display_name: '合同与交费', fields: [
        { field_key: 'cooling_off_period', short_title: '犹豫期', description: '投保人收到合同后可解除合同并退还保费的期间。', schema_category: '05 合同与交费规则' },
        { field_key: 'premium_grace_period', short_title: '宽限期', description: '到期未交保费后合同仍然有效的期间。', schema_category: '05 合同与交费规则' },
        { field_key: 'waiting_period', short_title: '等待期', description: '合同生效后一段时间内发生保险事故不赔付的期间。', schema_category: '06 保障责任' },
      ],
    }],
  })
}

function entity(id: string, name: string, label: string, entityType = 'insurance_product'): ReleaseMember {
  return member('entity', `entity/${id}`, { entity_id: id, entity_type: entityType, names: [name], classification_labels: [label] })
}

export const CONCEPT = member('concept', 'concept/cooling_off_period', {
  concept_key: 'cooling_off_period',
  title: '犹豫期',
  definition: '投保人收到合同后可解除合同并退还保费的期间。',
  explanation: '犹豫期是投保人签收保险合同后的一段冷静期，期间解除合同可退还已交保费。',
  statements: [
    { text: '甲医疗与乙医疗的犹豫期为15日。', refs: ['M1/cooling_off_period', 'M2/cooling_off_period'] },
    { text: '丙重疾的犹豫期为20日。', refs: ['C1/cooling_off_period'] },
  ],
  based_on: {
    'M1/cooling_off_period': 'a'.repeat(64),
    'M2/cooling_off_period': 'b'.repeat(64),
    'C1/cooling_off_period': 'c'.repeat(64),
  },
  origin: 'MODEL_GENERATED',
  model: 'deepseek-flash',
  prompt_version: 'concept-test',
})

export function release(options: { navigation?: boolean; concept?: boolean; changedDigest?: boolean } = {}): Release {
  const { navigation = true, concept = true, changedDigest = false } = options
  return {
    id: 'rel-9',
    epoch: 15,
    members: [
      ...(navigation ? [NAVIGATION] : []),
      profile('profile_medical', '医疗险', 'medical'),
      profile('profile_critical', '重疾险', 'critical'),
      entity('M1', '甲医疗', 'medical'),
      entity('M2', '乙医疗', 'medical'),
      entity('C1', '丙重疾', 'critical'),
      entity('X1', '丁未分组', 'unknown_label'),
      claim('M1', 'cooling_off_period', 'present', '自签收之日起15日。', 1, 'a'.repeat(64)),
      claim('M2', 'cooling_off_period', 'present', '1. 期间：自签收之日起15日。2. 退费：全额退还。3. 手续：书面申请。4. 其他：无。', 2, 'b'.repeat(64)),
      claim('C1', 'cooling_off_period', 'present', '自签收之日起20日，期间解除合同的，退还全部保费；超过犹豫期解除合同的，退还现金价值，并可能有损失。', 1, changedDigest ? 'e'.repeat(64) : 'c'.repeat(64)),
      claim('X1', 'cooling_off_period', 'unknown', null, 0),
      claim('M1', 'premium_grace_period', 'present', '60日。'),
      claim('C1', 'premium_grace_period', 'absent_explicitly', null),
      claim('M1', 'waiting_period', 'present', '90日。'),
      claim('M2', 'waiting_period', 'unknown', null, 0),
      ...(concept ? [CONCEPT] : []),
    ],
  }
}
