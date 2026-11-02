// @vitest-environment happy-dom
// PV-5 acceptance (protected, written by Claude): a sale status reference is a release member with no
// evidence to open. Only its exact tuple identifies it; its preview shows the status text, its tier
// is labelled as product registry data, and the citation explains that no source exists instead of
// reporting a broken one (Spec docs/design/slices/PV-5-问答销售状态与产品识别.md §1.3).
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import enUS from './i18n/messages/en-US'
import jaJP from './i18n/messages/ja-JP'
import koKR from './i18n/messages/ko-KR'
import ruRU from './i18n/messages/ru-RU'
import zhMessages from './i18n/messages/zh-CN'
import ReleaseCitation from './ReleaseCitation.vue'
import { releaseCitationPreview, releaseCitationTarget, releaseStatusReference } from './releaseReferences'
import { sourceTier, sourceTierLabel } from './sourceTier'

const status = (metadata: Record<string, unknown> = {}, id = 'release:rel-1:entity/P') => ({
  id, knowledge_title: '丁护理保险 · 销售状态', content: '丁护理保险 · 销售状态：停售',
  metadata: {
    source_tier: 'release', space_id: 's1', release_id: 'rel-1', logical_slug: 'entity/P',
    knowledge_class: 'sale_status', ...metadata,
  },
})

describe('sale status references', () => {
  it('are identified only by their exact tuple', () => {
    expect(releaseStatusReference(status())).toBe(true)
    expect(releaseStatusReference(status({ evidence_index: '0' }))).toBe(false)
    expect(releaseStatusReference(status({ knowledge_class: undefined }))).toBe(false)
    expect(releaseStatusReference(status({ logical_slug: 'P/waiting_period' }, 'release:rel-1:P/waiting_period'))).toBe(false)
    expect(releaseStatusReference(status({ source_tier: 'wiki_page' }))).toBe(false)
    expect(releaseStatusReference(status({ release_id: 'active' }, 'release:active:entity/P'))).toBe(false)
    expect(releaseStatusReference(status({}, 'release:other:entity/P'))).toBe(false)
    expect(releaseStatusReference(status({ space_id: '' }))).toBe(false)
  })

  it('open no source but preview their text', () => {
    expect(releaseCitationTarget(status())).toBeNull()
    expect(releaseCitationPreview(status().id, [status()], 'missing'))
      .toEqual({ title: '丁护理保险 · 销售状态', content: '丁护理保险 · 销售状态：停售' })
    const field = {
      id: status().id, knowledge_title: 'x', content: 'y',
      metadata: { source_tier: 'release', space_id: 's1', release_id: 'rel-1', logical_slug: 'entity/P', evidence_index: '0' },
    }
    expect(releaseCitationPreview(status().id, [status(), field], 'missing')?.error).toBe('missing')
  })

  it('carry their own tier label', () => {
    expect(sourceTier(status())).toBe('sale_status')
    expect(sourceTierLabel('sale_status', key => key)).toBe('chat.sourceTierSaleStatus')
    expect(sourceTier(status({ knowledge_class: undefined }))).toBe('release')
  })

  it('explain in the citation that no source exists', () => {
    const view = mount(ReleaseCitation, {
      props: { reference: status() },
      global: {
        plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
        stubs: { CitationPanel: true },
      },
    })
    expect(view.text()).toContain('销售状态由本版本的产品登记数据计算，没有原文出处。')
    expect(view.text()).not.toContain('此引用缺少准确出处')
    expect(view.findComponent({ name: 'CitationPanel' }).exists()).toBe(false)
  })

  it('have their strings in every enterprise locale', () => {
    expect(zhMessages.chat.sourceTierSaleStatus).toBe('销售状态（产品登记数据）')
    for (const messages of [zhMessages, enUS, jaJP, koKR, ruRU] as any[]) {
      expect(typeof messages.chat.sourceTierSaleStatus).toBe('string')
      expect(typeof messages.chat.releaseStatusNote).toBe('string')
    }
  })
})
