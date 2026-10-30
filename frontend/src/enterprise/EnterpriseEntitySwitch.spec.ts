// @vitest-environment happy-dom
// Regression (PR #188 review R2): the router reuses the entry page when only the entry changes.
// A citation opened for the previous entry must close; the pinned release is kept.
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
import { readRelease, type ReleaseMember } from './enterpriseApi'

function claim(subject: string): ReleaseMember {
  return {
    kind: 'claim', logical_slug: `${subject}/term`, member_digest: 'd'.repeat(64), access_scope: 'space',
    payload: { subject_ref: subject, predicate: 'term', state: 'present', value: subject, origin: 'SOURCE_SUPPORTED', evidence: [{}] },
  }
}

afterEach(() => { vi.resetAllMocks() })

describe('switching entries on a reused page', () => {
  it('closes the citation of the previous entry and keeps the release', async () => {
    vi.mocked(readRelease).mockResolvedValue({ id: 'rel-1', epoch: 1, members: [claim('P1'), claim('P2')] })
    const view = mount(EnterpriseEntity, {
      props: { spaceId: 'demo', entityId: 'P1', releaseId: 'rel-1' },
      global: {
        plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
        stubs: { RouterLink: RouterLinkStub, CitationPanel: true },
      },
    })
    await flushPromises()
    await view.get('[data-field="P1/term"] button').trigger('click')
    expect(view.getComponent(CitationPanel).props('member')).toBe('P1/term')

    await view.setProps({ entityId: 'P2' })
    await flushPromises()
    expect(view.findComponent(CitationPanel).exists()).toBe(false)
    expect(view.find('[data-field="P2/term"]').exists()).toBe(true)
    expect(readRelease).toHaveBeenCalledTimes(1)

    await view.get('[data-field="P2/term"] button').trigger('click')
    expect(view.getComponent(CitationPanel).props()).toMatchObject({ member: 'P2/term', releaseId: 'rel-1' })
  })
})
