// @vitest-environment happy-dom
// S3f acceptance (protected, written by Claude): the reading layout keeps every behaviour and adds
// only presentation hooks (Spec docs/design/slices/S3f-阅读排版.md §3).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import CitationPanel from './CitationPanel.vue'
import EnterpriseEntity from './EnterpriseEntity.vue'
import { readRelease, type Release, type ReleaseMember } from './enterpriseApi'

function member(kind: string, slug: string, payload: Record<string, unknown>): ReleaseMember {
  return { kind, logical_slug: slug, payload, member_digest: 'd'.repeat(64), access_scope: 'space' }
}

function release(): Release {
  return {
    id: 'rel-5',
    epoch: 5,
    members: [
      member('presentation_profile', 'presentation/profile_ci', {
        profile_id: 'profile_ci', display_name: '重疾险', classification_labels: ['ci'],
        sections: [{ section_key: 'terms', display_name: '条款', fields: [{ field_key: 'f_wait', short_title: '等待期' }] }],
      }),
      member('entity', 'entity/P1', { entity_id: 'P1', names: ['甲产品'], classification_labels: ['ci'] }),
      member('claim', 'P1/f_wait', {
        subject_ref: 'P1', predicate: 'f_wait', state: 'present', value: '90日', origin: 'SOURCE_SUPPORTED',
        evidence: [{ quote: 'q0' }, { quote: 'q1' }],
      }),
      member('claim', 'P1/f_note', {
        subject_ref: 'P1', predicate: 'f_note', state: 'present', value: '通用说明', origin: 'MODEL_GENERATED', evidence: [],
      }),
    ],
  }
}

function page() {
  return mount(EnterpriseEntity, {
    props: { spaceId: 'demo', entityId: 'P1', releaseId: 'rel-5' },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub, CitationPanel: true, EnterpriseNavigation: true },
    },
  })
}

afterEach(() => { vi.resetAllMocks() })

describe('reading layout', () => {
  it('names the insurance category and the release under the title', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    const meta = view.get('[data-entity-meta]')
    expect(meta.text()).toContain('重疾险')
    expect(meta.text()).toContain('发布版本 5')
  })

  it('shows each source as its own quiet chip that still opens that evidence', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    const chips = view.get('[data-field="P1/f_wait"]').findAll('button.ek-source-chip')
    expect(chips.map(chip => chip.text())).toEqual(['出处 1', '出处 2'])
    await chips[1].trigger('click')
    expect(view.getComponent(CitationPanel).props()).toMatchObject({ releaseId: 'rel-5', member: 'P1/f_wait', evidence: 1 })
  })

  it('keeps model-generated fields visibly apart', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    const field = view.get('[data-field="P1/f_note"]')
    expect(field.classes()).toContain('ek-field--generated')
    expect(field.get('[data-origin]').text()).toBe('模型补充')
  })
})
