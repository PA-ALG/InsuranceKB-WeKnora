// @vitest-environment happy-dom
// S9b acceptance (protected, written by Claude): a source that is an expert revision shows who
// changed what, when, from what to what and why, and opens no source page
// (Spec docs/design/slices/S9b-专家编辑界面.md §2.5).
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readCitation: vi.fn(),
}))

import CitationPanel from './CitationPanel.vue'
import SourcePageViewer from './SourcePageViewer.vue'
import { readCitation, type ExpertCitation } from './enterpriseApi'

const RECORDED = '2026-10-22T09:30:15.123456Z'

function revision(change: Partial<ExpertCitation> = {}): ExpertCitation {
  return {
    kind: 'expert_revision', release_id: 'rel-2', member: 'P1/f_wait', evidence_index: 0,
    origin: 'EXPERT_REVISION', quote: '180日', revision_record_id: 'rev-1',
    actor: 'web_user:zhang.san', role: 'admin', recorded_at: RECORDED,
    before: { state: 'present', value: '90日' }, after: { state: 'present', value: '180日' },
    reason: '备案条款第五条', ...change,
  }
}

function localMinute(iso: string): string {
  const at = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`
}

function panel() {
  return mount(CitationPanel, {
    props: { spaceId: 'demo', releaseId: 'rel-2', member: 'P1/f_wait', evidence: 0 },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { SourcePageViewer: true },
    },
  })
}

afterEach(() => { vi.resetAllMocks() })

describe('an expert revision source', () => {
  it('shows the revision record and no source page', async () => {
    vi.mocked(readCitation).mockResolvedValue(revision())
    const view = panel()
    await flushPromises()
    const record = view.get('[data-expert-revision]')
    const text = record.text()
    expect(text).toContain('zhang.san')
    expect(text).not.toContain('web_user:')
    expect(text).toContain('管理员')
    expect(text).toContain(localMinute(RECORDED))
    expect(text).toContain('90日')
    expect(text).toContain('180日')
    expect(text).toContain('备案条款第五条')
    expect(text.indexOf('90日')).toBeLessThan(text.indexOf('180日'))
    expect(view.get('[data-origin]').text()).toBe('专家修订')
    expect(view.findComponent(SourcePageViewer).exists()).toBe(false)
    expect(view.html()).not.toContain('/file')
  })

  it.each([
    ['owner', '所有者'],
    ['admin', '管理员'],
    ['auditor', 'auditor'],
  ])('labels the role %s', async (role, label) => {
    vi.mocked(readCitation).mockResolvedValue(revision({ role }))
    const view = panel()
    await flushPromises()
    expect(view.get('[data-expert-revision]').text()).toContain(label)
  })

  it('shows states without a value by their label', async () => {
    vi.mocked(readCitation).mockResolvedValue(revision({
      quote: '条款无此责任', before: { state: 'unknown', value: null },
      after: { state: 'absent_explicitly', value: null }, reason: '条款无此责任',
    }))
    const view = panel()
    await flushPromises()
    const text = view.get('[data-expert-revision]').text()
    expect(text).toContain('材料未提及')
    expect(text).toContain('材料明确没有')
    expect(text.indexOf('材料未提及')).toBeLessThan(text.indexOf('材料明确没有'))
  })
})
