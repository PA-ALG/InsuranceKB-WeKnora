// @vitest-environment happy-dom
// S3d-3a acceptance (protected, written by Claude): Space list, Space page and entity page
// (Spec docs/design/slices/S3d-3a-企业知识页面.md §3.3). Every citation an entity page opens is
// pinned to the release that page actually read.
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  listSpaces: vi.fn(),
  readRelease: vi.fn(),
  readCitation: vi.fn(),
}))

import CitationPanel from './CitationPanel.vue'
import EnterpriseEntity from './EnterpriseEntity.vue'
import EnterpriseSpace from './EnterpriseSpace.vue'
import EnterpriseSpaces from './EnterpriseSpaces.vue'
import { EnterpriseError, listSpaces, readRelease, type Release, type ReleaseMember } from './enterpriseApi'

function i18n() {
  return createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })
}

function page(component: any, props: Record<string, unknown> = {}) {
  return mount(component, {
    props,
    global: { plugins: [i18n()], stubs: { RouterLink: RouterLinkStub, CitationPanel: true } },
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(ok => { resolve = ok })
  return { promise, resolve }
}

function member(kind: string, slug: string, payload: Record<string, unknown>): ReleaseMember {
  return { kind, logical_slug: slug, payload, member_digest: 'd'.repeat(64), access_scope: 'space' }
}

function claim(predicate: string, state: string, value: unknown, origin: string, evidence: number) {
  return member('claim', `P1/${predicate}`, {
    subject_ref: 'P1', predicate, state, value, origin,
    evidence: Array.from({ length: evidence }, (_, index) => ({ quote: `q${index}` })),
  })
}

function release(id = 'rel-1'): Release {
  return {
    id,
    epoch: 3,
    members: [
      member('presentation_profile', 'presentation/profile_a', {
        profile_id: 'profile_a', classification_labels: ['class_a'],
        sections: [
          { section_key: 'overview', display_name: '概览', fields: [{ field_key: 'f_name', short_title: '名称' }] },
          { section_key: 'terms', display_name: '条款', fields: [
            { field_key: 'f_wait', short_title: '等待期' }, { field_key: 'f_grace', short_title: '宽限期' }] },
        ],
      }),
      member('entity', 'entity/P1', { entity_id: 'P1', names: ['乙产品'], classification_labels: ['class_a'] }),
      claim('f_grace', 'absent_explicitly', null, 'SOURCE_SUPPORTED', 1),
      claim('f_wait', 'present', '90日', 'SOURCE_SUPPORTED', 2),
      claim('f_name', 'present', ['A', 'B'], 'EXPERT_REVISION', 1),
      claim('z_extra', 'unknown', null, 'MIXED', 0),
      claim('f_concept', 'present', '通用解释', 'MODEL_GENERATED', 0),
      member('claim', 'P3/f_wait', { subject_ref: 'P3', predicate: 'f_wait', state: 'present', value: '1', origin: 'STRUCTURED_IMPORT', evidence: [] }),
    ],
  }
}

afterEach(() => { vi.resetAllMocks() })

describe('Space list', () => {
  it('loads the Spaces and links each to its page', async () => {
    const spaces = deferred<string[]>()
    vi.mocked(listSpaces).mockReturnValue(spaces.promise)
    const view = page(EnterpriseSpaces)
    expect(view.find('[role="status"]').exists()).toBe(true)
    spaces.resolve(['alpha', 'demo'])
    await flushPromises()
    const links = view.findAllComponents(RouterLinkStub)
    expect(links.map(link => link.props('to'))).toEqual([
      { name: 'enterpriseSpace', params: { spaceId: 'alpha' } },
      { name: 'enterpriseSpace', params: { spaceId: 'demo' } },
    ])
    expect(links.map(link => link.text())).toEqual(['alpha', 'demo'])
  })

  it('says when there is nothing to read', async () => {
    vi.mocked(listSpaces).mockResolvedValue([])
    const view = page(EnterpriseSpaces)
    await flushPromises()
    expect(view.text()).toContain('暂无可查看的企业知识空间')
    expect(view.findAllComponents(RouterLinkStub)).toHaveLength(0)
  })

  it('offers a retry after a failure', async () => {
    vi.mocked(listSpaces).mockRejectedValueOnce(new EnterpriseError('REQUEST_FAILED')).mockResolvedValueOnce(['demo'])
    const view = page(EnterpriseSpaces)
    await flushPromises()
    const alert = view.get('[role="alert"]')
    expect(alert.text()).toContain('企业知识空间加载失败')
    await alert.get('button').trigger('click')
    await flushPromises()
    expect(listSpaces).toHaveBeenCalledTimes(2)
    expect(view.findAllComponents(RouterLinkStub)).toHaveLength(1)
  })
})

describe('Space page', () => {
  it('reads the active release and links each entry to that same release', async () => {
    vi.mocked(readRelease).mockResolvedValue(release('rel-9'))
    const view = page(EnterpriseSpace, { spaceId: 'demo' })
    await flushPromises()
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo']])
    // S3f-2: the version is a quiet tag beside the title.
    expect(view.get('[data-space-version]').text()).toBe('版本 3')
    // S3e: the Space page also lists concept links; S3f-2 adds an overview table with its own entry
    // links. This case checks the navigation's entry links only.
    const links = view.findAll('[data-nav-entry]').flatMap(entry => entry.findAllComponents(RouterLinkStub))
      .filter(link => (link.props('to') as { name?: string }).name === 'enterpriseEntity')
    expect(links.map(link => link.props('to'))).toEqual([
      { name: 'enterpriseEntity', params: { spaceId: 'demo', entityId: 'P1' }, query: { release: 'rel-9' } },
      { name: 'enterpriseEntity', params: { spaceId: 'demo', entityId: 'P3' }, query: { release: 'rel-9' } },
    ])
    expect(links[0].text()).toContain('乙产品')
    // S3f-2: the navigation shows one line per entry; the field count is no longer listed.
  })

  it('treats a Space without a release as empty, not as an error', async () => {
    vi.mocked(readRelease).mockRejectedValue(new EnterpriseError('RELEASE_NOT_FOUND', 404))
    const view = page(EnterpriseSpace, { spaceId: 'demo' })
    await flushPromises()
    expect(view.text()).toContain('该空间还没有发布版本')
    expect(view.find('[role="alert"]').exists()).toBe(false)
  })

  it('offers a retry after other failures and shows an empty release as empty', async () => {
    vi.mocked(readRelease)
      .mockRejectedValueOnce(new EnterpriseError('SERVICE_UNAVAILABLE', 503))
      .mockResolvedValueOnce({ id: 'rel-1', epoch: 1, members: [] })
    const view = page(EnterpriseSpace, { spaceId: 'demo' })
    await flushPromises()
    expect(view.get('[role="alert"]').text()).toContain('发布版本加载失败')
    await view.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(view.text()).toContain('该版本中还没有条目')
  })
})

describe('entity page', () => {
  it('shows published fields by section with states, sources and model content apart', async () => {
    vi.mocked(readRelease).mockResolvedValue(release('rel-1'))
    const view = page(EnterpriseEntity, { spaceId: 'demo', entityId: 'P1', releaseId: 'rel-1' })
    await flushPromises()
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-1']])
    expect(view.text()).toContain('乙产品')
    expect(view.findAll('[data-section]').map(section => section.attributes('data-section'))).toEqual(['overview', 'terms'])
    const terms = view.get('[data-section="terms"]')
    expect(terms.text()).toContain('条款')
    expect(terms.findAll('[data-field]').map(field => field.attributes('data-field'))).toEqual(['P1/f_wait', 'P1/f_grace'])

    const wait = view.get('[data-field="P1/f_wait"]')
    expect(wait.text()).toContain('等待期')
    expect(wait.text()).toContain('90日')
    expect(wait.get('[data-origin]').text()).toBe('原文依据')
    expect(view.get('[data-field="P1/f_grace"]').text()).toContain('材料明确没有')
    const name = view.get('[data-field="P1/f_name"]')
    expect(name.text()).toContain('A')
    expect(name.text()).toContain('B')
    expect(name.get('[data-origin]').text()).toBe('专家修订')

    const other = view.get('[data-other]')
    expect(other.text()).toContain('其他')
    expect(other.get('[data-field="P1/z_extra"]').text()).toContain('材料未提及')
    expect(other.get('[data-field="P1/z_extra"] [data-origin]').text()).toBe('原文与整理')

    const generated = view.get('[data-generated]')
    expect(generated.text()).toContain('模型补充')
    expect(generated.get('[data-field="P1/f_concept"] [data-origin]').text()).toBe('模型补充')
    expect(view.findAll('[data-section] [data-field="P1/f_concept"]')).toHaveLength(0)
  })

  it('opens each evidence of a field on the release the page read', async () => {
    vi.mocked(readRelease).mockResolvedValue(release('rel-1'))
    const view = page(EnterpriseEntity, { spaceId: 'demo', entityId: 'P1', releaseId: 'rel-1' })
    await flushPromises()
    const buttons = view.get('[data-field="P1/f_wait"]').findAll('button')
    expect(buttons.map(button => button.text())).toEqual(['出处 1', '出处 2'])
    expect(view.findComponent(CitationPanel).exists()).toBe(false)
    await buttons[1].trigger('click')
    expect(view.getComponent(CitationPanel).props()).toMatchObject({
      spaceId: 'demo', releaseId: 'rel-1', member: 'P1/f_wait', evidence: 1,
    })
  })

  it('pins citations to the release actually read when none was named', async () => {
    vi.mocked(readRelease).mockResolvedValue(release('rel-7'))
    const view = page(EnterpriseEntity, { spaceId: 'demo', entityId: 'P1' })
    await flushPromises()
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo']])
    await view.get('[data-field="P1/f_grace"] button').trigger('click')
    expect(view.getComponent(CitationPanel).props()).toMatchObject({ releaseId: 'rel-7', member: 'P1/f_grace', evidence: 0 })
  })

  it('says when the release does not hold the entry and retries after a failure', async () => {
    vi.mocked(readRelease).mockResolvedValueOnce(release())
    const missing = page(EnterpriseEntity, { spaceId: 'demo', entityId: 'nope', releaseId: 'rel-1' })
    await flushPromises()
    expect(missing.text()).toContain('该版本中没有这个条目')

    vi.mocked(readRelease).mockRejectedValueOnce(new EnterpriseError('REQUEST_FAILED')).mockResolvedValueOnce(release())
    const failing = page(EnterpriseEntity, { spaceId: 'demo', entityId: 'P1', releaseId: 'rel-1' })
    await flushPromises()
    expect(failing.get('[role="alert"]').text()).toContain('条目加载失败')
    await failing.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(failing.find('[data-field="P1/f_wait"]').exists()).toBe(true)
  })
})
