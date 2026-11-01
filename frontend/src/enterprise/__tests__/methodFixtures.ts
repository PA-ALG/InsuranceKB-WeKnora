// SK-3 acceptance fixtures (protected, written by Claude): a release with three products and three
// sales methods (Spec docs/design/slices/SK-3-销售方法阅读与问答.md §5). sm-1 is tied to P1's family,
// labelled 医疗 and 需求分析, carries the product_info notice and cites material A item by item; sm-3
// (listed before sm-1) is labelled 医疗 only; sm-2 is general and cites material B. P3 is unrelated.
// Synthetic data only.
import type { Release, ReleaseMember } from '../enterpriseApi'
import { member } from './s3eFixtures'

const SHA = 'ab'.repeat(32)
export const MATERIAL_A = `source:v1:kA:1:${SHA}`
export const MATERIAL_B = `source:v1:kB:2:${SHA}`

const NAVIGATION = member('navigation', 'navigation/enterprise', {
  navigation_id: 'enterprise',
  navigation_version: 'v2',
  domains: [
    {
      domain_key: 'product', display_name: '产品库', entity_types: ['insurance_product'],
      groups: [
        { group_key: 'pack_medical', display_name: '医疗险', classification_labels: ['medical'] },
        { group_key: 'pack_critical', display_name: '重疾险', classification_labels: ['critical'] },
      ],
    },
    {
      domain_key: 'sales_method', display_name: '销售方法', entity_types: ['sales_method'],
      groups: [
        { group_key: 'medical', display_name: '医疗险', classification_labels: ['medical'] },
        { group_key: 'general', display_name: '通用', classification_labels: ['scope:general'] },
        { group_key: 'needs', display_name: '需求分析', classification_labels: ['sales_stage:needs_analysis'] },
      ],
    },
  ],
})

const PRODUCT_PROFILE = member('presentation_profile', 'presentation/medical', {
  profile_id: 'medical', display_name: '医疗险', classification_labels: ['medical', 'critical'],
  sections: [{ section_key: 'main', display_name: '基本信息', fields: [
    { field_key: 'waiting_period', short_title: '等待期' },
    { field_key: 'method_steps', short_title: '产品步骤' },
  ] }],
})

const METHOD_PROFILE = member('presentation_profile', 'presentation/sales_method', {
  profile_id: 'sales_method', display_name: '销售方法', entity_types: ['sales_method'], knowledge_class: 'method',
  reading_note: '销售方法（培训材料，非产品事实）：只用于怎么讲。',
  notices: { product_info: '其中的产品信息以条款与已发布知识为准。' },
  sections: [{ section_key: 'method', display_name: '销售方法', fields: [
    { field_key: 'method_summary', short_title: '方法摘要' },
    { field_key: 'method_steps', short_title: '步骤' },
    { field_key: 'key_phrases', short_title: '关键句' },
  ] }],
})

function product(id: string, label: string, name: string, extra: Record<string, unknown> = {}): ReleaseMember {
  return member('entity', `entity/${id}`, {
    entity_id: id, entity_type: 'insurance_product', names: [name], classification_labels: [label], ...extra,
  })
}

function method(id: string, labels: string[], name: string, notice = ''): ReleaseMember {
  return member('entity', `entity/${id}`, {
    entity_id: id, entity_type: 'sales_method', names: [name], classification_labels: labels,
    identifiers: notice ? { notice } : {},
  })
}

function cite(ref: string, quote: string, page: number) {
  return { source_ref: ref, quote, locator: { kind: 'PDF_TEXT_SPAN', page, start: 0, end: quote.length } }
}

function claim(subject: string, predicate: string, state: string, value: unknown, evidence: unknown[], changedAt?: string) {
  return member('claim', `${subject}/${predicate}`, {
    subject_ref: subject, predicate, state, value, origin: 'SOURCE_SUPPORTED', evidence,
    ...(changedAt ? { maintenance: { revision_no: 1, changed_by: 'compile', changed_at: changedAt } } : {}),
  })
}

export function methodRelease(): Release {
  return {
    id: 'rel-m', epoch: 4, members: [
      NAVIGATION, PRODUCT_PROFILE, METHOD_PROFILE,
      product('P1', 'medical', '甲医疗保险', { product_family: { key: 'fam', display_name: '甲医疗系列' } }),
      product('P2', 'medical', '乙医疗保险'),
      product('P3', 'critical', '丙重疾保险'),
      method('sm-3', ['medical'], '说明会邀约法'),
      method('sm-1', ['medical', 'family:fam', 'sales_stage:needs_analysis'], '需求分析三步法', 'product_info'),
      method('sm-2', ['scope:general'], '异议处理法'),
      claim('P1', 'waiting_period', 'present', '30日', [cite(MATERIAL_B, '等待期30日', 1)]),
      claim('P2', 'waiting_period', 'present', '60日', [cite(MATERIAL_B, '等待期60日', 2)]),
      claim('P3', 'waiting_period', 'present', '90日', [cite(MATERIAL_B, '等待期90日', 3)]),
      claim('sm-1', 'method_summary', 'present', '先问需求再讲产品', [cite(MATERIAL_A, '先问需求', 2)],
        '2026-10-28T03:00:00+00:00'),
      claim('sm-1', 'method_steps', 'present', ['问家庭', '讲保障'],
        [cite(MATERIAL_A, '问家庭', 3), cite(MATERIAL_A, '讲保障', 4)], '2026-10-30T01:00:00+00:00'),
      claim('sm-1', 'key_phrases', 'unknown', null, []),
      claim('sm-2', 'method_summary', 'present', '处理客户异议的方法', [cite(MATERIAL_B, '处理客户异议', 5)]),
      claim('sm-3', 'method_summary', 'present', '邀约客户参加说明会', [cite(MATERIAL_B, '邀约', 6)]),
    ],
  }
}
