import type { ConfirmationAnswer, ConfirmationItem } from '../enterpriseApi'

export function confirmationItem(id = 'item-1', extra: Partial<ConfirmationItem> = {}): ConfirmationItem {
  return {
    id, space_id: 'demo', subject: 'submitter:subject-1', revision: 'rev-7', content_digest: 'c'.repeat(64),
    title: '一份材料需要确认归属', detail: '第一行说明\n第二行说明',
    options: [{ key: 'replace', label: '替换原有文件' }, { key: 'supplement', label: '作为补充材料' }, { key: 'ignore', label: '忽略这份文件' }],
    created_by: 'service:submitter', created_at: '2026-10-25T08:00:00Z', ...extra,
  }
}

export function confirmationAnswer(itemId = 'item-1', extra: Partial<ConfirmationAnswer> = {}): ConfirmationAnswer {
  return { id: 'answer-1', item_id: itemId, option_key: 'supplement', note: '保留两份', answerer: 'user:alice',
    answered_at: '2026-10-25T09:00:00Z', ...extra }
}
