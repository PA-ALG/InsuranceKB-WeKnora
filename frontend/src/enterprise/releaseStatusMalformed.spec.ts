// @vitest-environment happy-dom
// PV-5 acceptance (protected, written by Claude, #530 R1): a reference marked as a sale status never
// becomes an ordinary evidence reference. A malformed one, such as the status tuple with an
// evidence index added, is refused at the source boundary and mounts no source panel; ordinary
// field and method references still open (Spec docs/design/slices/PV-5-问答销售状态与产品识别.md §1.3).
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import ReleaseCitation from './ReleaseCitation.vue'
import { releaseCitationPreview, releaseCitationTarget } from './releaseReferences'

const reference = (metadata: Record<string, unknown>, slug = 'entity/P') => ({
  id: `release:rel-1:${slug}`, knowledge_title: '丁护理保险 · 销售状态', content: '丁护理保险 · 销售状态：停售',
  metadata: { source_tier: 'release', space_id: 's1', release_id: 'rel-1', logical_slug: slug, ...metadata },
})
const malformed = [
  reference({ knowledge_class: 'sale_status', evidence_index: '0' }),
  reference({ knowledge_class: 'sale_status', evidence_index: '0' }, 'P/waiting_period'),
]

function cite(value: ReturnType<typeof reference>) {
  return mount(ReleaseCitation, {
    props: { reference: value },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { CitationPanel: true },
    },
  })
}

describe('malformed sale status references', () => {
  it('are no evidence target and preview as unavailable', () => {
    for (const value of malformed) {
      expect(releaseCitationTarget(value)).toBeNull()
      expect(releaseCitationPreview(value.id, [value], 'missing')?.error).toBe('missing')
    }
  })

  it('mount no source panel', () => {
    for (const value of malformed) {
      const view = cite(value)
      expect(view.findComponent({ name: 'CitationPanel' }).exists()).toBe(false)
      expect(view.text()).toContain('此引用缺少准确出处，无法打开。')
      expect(view.text()).not.toContain('销售状态由本版本的产品登记数据计算')
    }
  })

  it('leave ordinary field and method references openable', () => {
    for (const value of [
      reference({ evidence_index: '0' }, 'P/waiting_period'),
      reference({ knowledge_class: 'method', evidence_index: '0' }, 'M/steps'),
    ]) {
      expect(releaseCitationTarget(value)).not.toBeNull()
      expect(cite(value).findComponent({ name: 'CitationPanel' }).exists()).toBe(true)
    }
  })
})
