// @vitest-environment happy-dom
// RV4b acceptance (protected, written by Claude): the spot-check desk lists samples by release,
// shows each sampled field as published in that release with its sources pinned there, and
// records a person's verdict (Spec docs/design/slices/RV4-发布后抽检.md §2.2).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
  listSamples: vi.fn(),
  submitVerdict: vi.fn(),
}))

import CitationPanel from './CitationPanel.vue'
import EnterpriseSpace from './EnterpriseSpace.vue'
import EnterpriseSpotChecks from './EnterpriseSpotChecks.vue'
import {
  EnterpriseError, listSamples, readRelease, submitVerdict,
  type Release, type ReleaseMember, type SpotSample,
} from './enterpriseApi'

function member(kind: string, slug: string, payload: Record<string, unknown>, digest = 'd'.repeat(64)): ReleaseMember {
  return { kind, logical_slug: slug, payload, member_digest: digest, access_scope: 'space' }
}

function release(id: string, epoch: number, value: string): Release {
  return {
    id, epoch,
    members: [
      member('presentation_profile', 'presentation/profile_ci', {
        profile_id: 'profile_ci', display_name: '重疾险', classification_labels: ['ci'],
        sections: [{ section_key: 'terms', display_name: '条款', fields: [{ field_key: 'f_wait', short_title: '等待期' }] }],
      }),
      member('entity', 'entity/P1', { entity_id: 'P1', names: ['甲产品'], classification_labels: ['ci'] }),
      member('claim', 'P1/f_wait', {
        subject_ref: 'P1', predicate: 'f_wait', state: 'present', value, origin: 'SOURCE_SUPPORTED',
        evidence: [{ quote: 'q0' }, { quote: 'q1' }],
      }),
    ],
  }
}

function sample(id: string, releaseId: string, extra: Partial<SpotSample> = {}): SpotSample {
  return {
    id, space_id: 'demo', release_id: releaseId, logical_slug: 'P1/f_wait', member_digest: 'd'.repeat(64),
    stratum: 'pack/must', created_by: 'svc', created_at: '2026-10-18T12:00:00Z', ...extra,
  }
}

function releases(id?: string) {
  return Promise.resolve(id === 'rel-2' ? release('rel-2', 2, '60日') : release('rel-1', 1, '90日'))
}

function page() {
  return mount(EnterpriseSpotChecks, {
    props: { spaceId: 'demo' },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub, CitationPanel: true },
    },
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

afterEach(() => { vi.resetAllMocks() })

describe('spot-check desk', () => {
  it('lists pending samples by release, each field as that release published it', async () => {
    vi.mocked(listSamples).mockResolvedValue([sample('s1', 'rel-1'), sample('s2', 'rel-2'), sample('s3', 'rel-1', { logical_slug: 'P9/x' })])
    vi.mocked(readRelease).mockImplementation((_space, id) => releases(id))
    const view = page()
    await flushPromises()
    expect(vi.mocked(listSamples).mock.calls).toEqual([['demo', 'pending']])
    // Each release is read once, by its own id, never the active one.
    expect(vi.mocked(readRelease).mock.calls.map(call => call[1]).sort()).toEqual(['rel-1', 'rel-2'])
    const groups = view.findAll('[data-spot-release]')
    expect(groups.map(group => group.attributes('data-spot-release'))).toEqual(['rel-1', 'rel-2'])
    expect(groups[0].text()).toContain('发布版本 1')
    const first = view.get('[data-spot-sample="s1"]')
    expect(first.text()).toContain('甲产品')
    expect(first.text()).toContain('等待期')
    expect(first.text()).toContain('90日')
    expect(view.get('[data-spot-sample="s2"]').text()).toContain('60日')
    // A sampled member the release does not hold is shown as such and cannot be judged.
    const missing = view.get('[data-spot-sample="s3"]')
    expect(missing.text()).toContain('该条目已变化')
    expect(missing.findAll('[data-verdict]').every(button => button.attributes('disabled') !== undefined)).toBe(true)
  })

  it('opens a sample\'s sources on the sample\'s own release', async () => {
    vi.mocked(listSamples).mockResolvedValue([sample('s2', 'rel-2')])
    vi.mocked(readRelease).mockImplementation((_space, id) => releases(id))
    const view = page()
    await flushPromises()
    const sources = view.get('[data-spot-sample="s2"]').findAll('button').filter(button => button.text() === '出处 2')
    await sources[0].trigger('click')
    expect(view.getComponent(CitationPanel).props()).toMatchObject({ spaceId: 'demo', releaseId: 'rel-2', member: 'P1/f_wait', evidence: 1 })
  })

  it('records a verdict with its note, then moves the sample out of the pending list', async () => {
    vi.mocked(listSamples).mockResolvedValue([sample('s1', 'rel-1')])
    vi.mocked(readRelease).mockImplementation((_space, id) => releases(id))
    const pending = deferred<unknown>()
    vi.mocked(submitVerdict).mockReturnValue(pending.promise as never)
    const view = page()
    await flushPromises()
    const card = view.get('[data-spot-sample="s1"]')
    await card.get('textarea').setValue('缺少等待期起算日')
    await card.get('[data-verdict="wrong"]').trigger('click')
    expect(vi.mocked(submitVerdict).mock.calls).toEqual([['demo', 's1', 'wrong', '缺少等待期起算日']])
    expect(card.findAll('[data-verdict]').every(button => button.attributes('disabled') !== undefined)).toBe(true)
    pending.resolve({ id: 'v1', sample_id: 's1', outcome: 'wrong', note: '缺少等待期起算日', reviewer: 'user:alice', decided_at: '2026-10-18T12:30:00Z' })
    await flushPromises()
    expect(view.find('[data-spot-sample="s1"]').exists()).toBe(false)
  })

  it('keeps the sample after a failed verdict, offers a retry, and names a missing permission', async () => {
    vi.mocked(listSamples).mockResolvedValue([sample('s1', 'rel-1')])
    vi.mocked(readRelease).mockImplementation((_space, id) => releases(id))
    vi.mocked(submitVerdict)
      .mockRejectedValueOnce(new EnterpriseError('REQUEST_FAILED'))
      .mockRejectedValueOnce(new EnterpriseError('RELEASE_ACCESS_DENIED', 403))
    const view = page()
    await flushPromises()
    const card = view.get('[data-spot-sample="s1"]')
    await card.get('[data-verdict="correct"]').trigger('click')
    await flushPromises()
    expect(card.get('[role="alert"]').text()).toContain('结论提交失败')
    expect(card.get('[data-verdict="correct"]').attributes('disabled')).toBeUndefined()
    await card.get('[data-verdict="correct"]').trigger('click')
    await flushPromises()
    expect(card.get('[role="alert"]').text()).toContain('没有确认权限')
    expect(vi.mocked(submitVerdict)).toHaveBeenCalledTimes(2)
  })

  it('shows decided samples with their verdict, note and reviewer', async () => {
    vi.mocked(listSamples).mockImplementation((_space, status) => Promise.resolve(status === 'decided'
      ? [sample('s9', 'rel-1', { verdict: { id: 'v9', sample_id: 's9', outcome: 'incomplete', note: '缺少一项', reviewer: 'user:alice', decided_at: '2026-10-18T12:30:00Z' } })]
      : []))
    vi.mocked(readRelease).mockImplementation((_space, id) => releases(id))
    const view = page()
    await flushPromises()
    await view.get('[data-spot-tab="decided"]').trigger('click')
    await flushPromises()
    expect(vi.mocked(listSamples).mock.calls).toEqual([['demo', 'pending'], ['demo', 'decided']])
    const card = view.get('[data-spot-sample="s9"]')
    expect(card.text()).toContain('不完整')
    expect(card.text()).toContain('缺少一项')
    expect(card.text()).toContain('user:alice')
    expect(card.find('[data-verdict]').exists()).toBe(false)
  })

  it('says when nothing waits and retries after a failed load', async () => {
    vi.mocked(listSamples).mockResolvedValueOnce([])
    const empty = page()
    await flushPromises()
    expect(empty.text()).toContain('没有待确认的样本')

    vi.mocked(listSamples).mockRejectedValueOnce(new EnterpriseError('SERVICE_UNAVAILABLE', 503)).mockResolvedValueOnce([])
    const failing = page()
    await flushPromises()
    const alert = failing.get('[role="alert"]')
    expect(alert.text()).toContain('抽检样本加载失败')
    await alert.get('button').trigger('click')
    await flushPromises()
    expect(failing.text()).toContain('没有待确认的样本')
  })

  it('is reachable from the Space page', async () => {
    vi.mocked(readRelease).mockResolvedValue(release('rel-1', 1, '90日'))
    const view = mount(EnterpriseSpace, {
      props: { spaceId: 'demo' },
      global: {
        plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
        stubs: { RouterLink: RouterLinkStub },
      },
    })
    await flushPromises()
    const links = view.findAllComponents(RouterLinkStub).map(link => link.props('to'))
    expect(links).toContainEqual({ name: 'enterpriseSpotChecks', params: { spaceId: 'demo' } })
  })
})
