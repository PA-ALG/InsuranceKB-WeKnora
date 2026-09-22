// @vitest-environment happy-dom
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import ConceptPage from './ConceptFreeWiki830G2.vue'
enableAutoUnmount(afterEach)

const mocks = vi.hoisted(() => ({ read: vi.fn(), get: vi.fn(), loadPreparation: vi.fn(), loadActive: vi.fn(), readBatch: vi.fn(), readPinned: vi.fn() }))
const route = reactive({ params: { kbId: 'wiki-a', memberId: 'concept-a' }, query: {} as Record<string, unknown> })
vi.mock('vue-router', () => ({ useRoute: () => route }))
vi.mock('@/utils/request', () => ({ get: mocks.get }))
vi.mock('@/api/schema-wiki/conceptFreeWiki830G2', () => ({
  readConceptPage830G2: mocks.read, conceptCitationTransport830G2: (_session: unknown, io: any) => ({ getAuthority: io.get, getBytesByToken: io.getBytes }),
}))
vi.mock('@/api/schema-wiki/batchConcept830G3', () => ({
  loadBatchConceptPreparation830G3: mocks.loadPreparation,
  loadBatchConceptActive830G3: mocks.loadActive,
  readBatchConceptPage830G3: mocks.readBatch,
  readPinnedBatchConceptPage830G3: mocks.readPinned,
}))
vi.mock('@/components/schema-wiki/pdfJsPort', () => ({ createPdfJsPort: () => ({}) }))
const stubs = { RouterLink: { props: ['to'], template: '<a :data-target="JSON.stringify(to)"><slot /></a>' },
  ConceptCitationViewer830G2: { props: ['session', 'previewTransport'], template: '<div data-testid="source-viewer">{{session.read.release_id}}</div>' },
  SettingDrawer: { props: ['visible'], template: '<aside v-if="visible"><slot /></aside>' } }
function response() {
  return { scope: {}, read: { contract: 'concept-page-read.830.g2.v1', read_mode: 'current',
    release_id: 'release-a', activation_epoch: 4, member: { kind: 'concept', member_id: 'concept-a',
      owner_id: 'space-a', title: '被保险人', content: '被保险人就是受保险合同保障的人。', payload: {} },
    related_members: [{ kind: 'field_assertion', member_id: 'assertion-a', owner_id: 'entity-a',
      title: '投保范围', content: '符合承保条件', payload: { state: 'present', entity_version: 'v1' } },
      { kind: 'field_assertion', member_id: 'assertion-b', owner_id: 'entity-b', title: '常住地',
        content: '未知：未发现', payload: { state: 'unknown', entity_version: 'v2' } }],
    citations: [{ citation_id: 'citation-123', page_number: 1, quote: '被保险人' }] } }
}
beforeEach(() => {
  mocks.read.mockReset(); mocks.get.mockReset(); mocks.loadPreparation.mockReset(); mocks.loadActive.mockReset()
  mocks.readPinned.mockReset(); mocks.readPinned.mockResolvedValue(null);
  mocks.readBatch.mockReset(); route.query = {}; mocks.read.mockResolvedValue(response()); mocks.loadActive.mockResolvedValue(null)
})
describe('G2 shared concept page', () => {
  it('shows the shared definition and entity-specific tri-state fields with pinned links', async () => {
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises()
    expect(wrapper.text()).toContain('受保险合同保障')
    expect(wrapper.text()).toContain('entity-a'); expect(wrapper.text()).toContain('待补充')
    expect(wrapper.find('[data-target]').attributes('data-target')).toContain('release-a')
  })
  it('opens the G2 source viewer using the release that supplied the page', async () => {
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises()
    await wrapper.get('[data-testid="g2-source"]').trigger('click')
    expect(wrapper.get('[data-testid="source-viewer"]').text()).toBe('release-a')
  })
  it('does not show stale content after a failed fixed-release read', async () => {
    route.query = { release_id: 'release-missing' }; mocks.read.mockRejectedValue(new Error('missing'))
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises()
    expect(wrapper.text()).toContain('页面读取失败')
    expect(wrapper.text()).not.toContain('受保险合同保障')
  })
})

describe('G2 source preview under slow source verification', () => {
  it('allows a verified source taking 95 seconds while preserving binary response handling', async () => {
    mocks.get.mockImplementation((_path: string, config?: any) => {
      if ((config?.timeout ?? 30000) < 95000) return Promise.reject(new Error('timeout'));
      return Promise.resolve(config?.responseType === 'arraybuffer' ? new Uint8Array([37,80,68,70]).buffer : { verified: true });
    });
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises();
    await wrapper.get('[data-testid="g2-source"]').trigger('click');
    const io = wrapper.findComponent(stubs.ConceptCitationViewer830G2).props('previewTransport') as any;
    await expect(io.getAuthority('/authority')).resolves.toEqual({ verified: true });
    await expect(io.getBytesByToken('/content')).resolves.toEqual(new Uint8Array([37,80,68,70]));
    const calls = mocks.get.mock.calls.slice(-2);
    expect(calls.every((call: any[]) => call[1].timeout > 95000 && call[1].timeout <= 180000)).toBe(true);
    mocks.get.mockClear(); mocks.get.mockRejectedValue(new Error('source unavailable'));
    await expect(io.getAuthority('/authority')).rejects.toThrow('source unavailable');
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });
});

describe('G3 batch concept page modes', () => {
  const field = { kind: 'field_assertion', member_id: 'assertion-g3', owner_id: 'entity-g3', title: '等待期',
    content: '值：30天\n条件：首次投保\n例外：意外伤害\n有效期：保单年度内', payload: { state: 'present', value: '30天',
      entity_version: 'entity-g3@v1', conditions: ['首次投保'], exceptions: ['意外伤害'], valid_time: '保单年度内',
      evidence: [{ page_number: 8, quote: '本产品等待期为30天' }] } }
  const directory = { mode: 'g3-preparation', preparationID: 'preparation-g3', statusLabel: '待审核',
    scope: { wiki_kb_id: 'wiki-a' }, members: [field], entities: [] }

  function entityDirectory() {
    const overview = { ...field, kind: 'entity_overview', member_id: 'overview-g3', title: '示例医疗险', payload: {} }
    const freeWiki = { ...overview, kind: 'free_wiki', member_id: 'free-g3' }
    return { ...directory, members: [field, overview, freeWiki], entities: [{
      entityID: field.owner_id, entityVersion: '2026版', displayName: '示例医疗险',
      primaryClassification: 'medical_insurance', overview, freeWiki,
      sections: [{ sectionKey: 'contract', displayName: '合同规则',
        fields: [{ fieldKey: 'waiting_period', shortTitle: '等待期', memberID: field.member_id }] },
      { sectionKey: 'claims', displayName: '理赔规则', fields: [] }],
    }] }
  }

  it('keeps entity, Profile section and independent field navigation on a field page', async () => {
    route.query = { preparation_id: 'preparation-g3' }
    const scoped = entityDirectory()
    mocks.loadPreparation.mockResolvedValue(scoped)
    mocks.readBatch.mockResolvedValue({ readMode: 'preparation', directory: scoped, member: field, relatedMembers: [], citations: [] })
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises()
    const navigation = wrapper.get('nav[aria-label="实体知识导航"]')
    expect(navigation.text()).toContain('示例医疗险')
    expect(navigation.text()).toContain('合同规则')
    expect(wrapper.text()).toContain('2026版')
    const targets = navigation.findAll('a').map(node => JSON.parse(node.attributes('data-target')!))
    expect(targets).toContainEqual({ name: 'conceptPage830G2', params: { kbId: 'wiki-a', memberId: 'assertion-g3' },
      query: { preparation_id: 'preparation-g3' } })
    expect(targets).toContainEqual({ name: 'conceptPage830G2', params: { kbId: 'wiki-a', memberId: 'overview-g3' },
      query: { preparation_id: 'preparation-g3', section: 'contract' } })
  })

  it('opens a Profile section directly and rejects a section on a field page', async () => {
    const scoped = entityDirectory()
    route.query = { preparation_id: 'preparation-g3', section: 'contract' }
    mocks.loadPreparation.mockResolvedValue(scoped)
    mocks.readBatch.mockResolvedValue({ readMode: 'preparation', directory: scoped,
      member: scoped.entities[0]!.overview, relatedMembers: [], citations: [] })
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('[aria-label="实体字段"]').text()).toContain('合同规则')
    expect(wrapper.get('[aria-label="实体字段"]').text()).not.toContain('理赔规则')
    mocks.readBatch.mockResolvedValue({ readMode: 'preparation', directory: scoped, member: field, relatedMembers: [], citations: [] })
    route.params.memberId = 'assertion-g3'; await flushPromises()
    expect(wrapper.text()).toContain('页面读取失败')
    expect(wrapper.text()).not.toContain('值：30天')
  })

  it('refreshes a historical section using its own release, epoch and Profile', async () => {
    route.params.memberId = 'overview-g3'
    route.query = { release_id: 'release-old', section: 'contract' }
    const scoped = { ...entityDirectory(), mode: 'g3-active', releaseID: 'release-old', activationEpoch: 4 }
    const overview = scoped.entities[0]!.overview
    mocks.loadActive.mockResolvedValue({ ...scoped, releaseID: 'release-new', activationEpoch: 9, entities: [] })
    mocks.readPinned.mockResolvedValue({ readMode: 'active', directory: scoped, member: overview, relatedMembers: [], citations: [],
      session: { scope: scoped.scope, read: { ...response().read, release_id: 'release-old', activation_epoch: 4,
        member: overview, related_members: [], citations: [] } } })
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('[aria-label="实体字段"]').text()).toContain('合同规则')
    const targets = wrapper.get('nav').findAll('a').map(node => JSON.parse(node.attributes('data-target')!))
    expect(targets).toContainEqual({ name: 'conceptPage830G2', params: { kbId: 'wiki-a', memberId: 'assertion-g3' },
      query: { release_id: 'release-old' } })
    expect(mocks.readPinned).toHaveBeenCalledWith('wiki-a', 'overview-g3', 'release-old', expect.any(Object))
    expect(mocks.loadActive).not.toHaveBeenCalled()
    expect(mocks.read).not.toHaveBeenCalled()
    route.query = { release_id: 'release-old', section: 'new-version-only-section' }; await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  })

  it('renders preparation evidence locally and never requests an Active token or content', async () => {
    route.query = { preparation_id: 'preparation-g3' }
    mocks.loadPreparation.mockResolvedValue(directory)
    mocks.readBatch.mockResolvedValue({ readMode: 'preparation', directory, member: field, relatedMembers: [], citations: [] })
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises()
    expect(mocks.loadPreparation).toHaveBeenCalledWith('wiki-a', 'preparation-g3', expect.any(Object))
    expect(mocks.loadActive).not.toHaveBeenCalled(); expect(mocks.read).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('待审核')
    expect(wrapper.text()).toContain('本产品等待期为30天')
    expect(wrapper.text()).toContain('第 8 页')
    expect(wrapper.text()).toContain('激活后可打开原件')
    expect(wrapper.text()).toContain('首次投保')
    expect(wrapper.text()).toContain('意外伤害')
    expect(wrapper.text()).toContain('保单年度内')
    expect(wrapper.find('[data-testid="source-viewer"]').exists()).toBe(false)
    expect(mocks.get).not.toHaveBeenCalled()
  })

  it('uses the pinned shared page session for Active evidence', async () => {
    route.query = { release_id: 'release-g3' }
    const active = { ...directory, mode: 'g3-active', releaseID: 'release-g3', activationEpoch: 6 }
    const read = { contract: 'concept-page-read.830.g2.v1', read_mode: 'pinned', release_id: 'release-g3',
      activation_epoch: 6, member: field, related_members: [],
      citations: [{ citation_id: 'citation-123', page_number: 8, quote: '本产品等待期为30天' }] }
    mocks.loadActive.mockResolvedValue(active)
    mocks.readPinned.mockResolvedValue({ readMode: 'active', directory: active, member: field, relatedMembers: [],
      citations: read.citations, session: { scope: active.scope, read } })
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises()
    expect(mocks.read).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="g3-source"]').trigger('click')
    expect(wrapper.get('[data-testid="source-viewer"]').text()).toBe('release-g3')
  })

  it('rejects mixed preparation and release modes before reading either page', async () => {
    route.query = { preparation_id: 'preparation-g3', release_id: 'release-g3' }
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises()
    expect(wrapper.text()).toContain('页面读取失败')
    expect(mocks.loadPreparation).not.toHaveBeenCalled(); expect(mocks.loadActive).not.toHaveBeenCalled()
    expect(mocks.read).not.toHaveBeenCalled()
  })
})

describe('G3 exact release directory reuse while switching fields', () => {
  function page(memberID = 'field-one', releaseID = 'release-cache') {
    const source = response()
    const member = { ...source.read.member, member_id: memberID, content: memberID }
    const directory = { mode: 'g3-active', releaseID, activationEpoch: 4,
      scope: { wiki_kb_id: 'wiki-a' }, members: [member], entities: [] }
    return { readMode: 'active', directory, member, relatedMembers: [], citations: [],
      session: { ...source, read: { ...source.read, release_id: releaseID, member, related_members: [], citations: [] } } }
  }
  beforeEach(() => {
    route.params = { kbId: 'wiki-a', memberId: 'field-one' }
    route.query = { release_id: 'release-cache' }
  })
  afterEach(() => { route.params = { kbId: 'wiki-a', memberId: 'concept-a' } })
  it('fetches only the next member after a successful exact-release directory load', async () => {
    const first = page(); mocks.readPinned.mockResolvedValue(first)
    mocks.readBatch.mockResolvedValue({ ...page('field-two'), directory: first.directory })
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises()
    route.params.memberId = 'field-two'; await flushPromises()
    expect(mocks.readPinned).toHaveBeenCalledTimes(1)
    expect(mocks.readBatch).toHaveBeenCalledWith(first.directory, 'field-two', expect.anything())
    expect(wrapper.text()).toContain('field-two')
  })
  it('discards the directory when a member read fails or the release changes', async () => {
    mocks.readPinned.mockResolvedValue(page())
    mocks.readBatch.mockRejectedValue(new Error('access revoked'))
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises()
    route.params.memberId = 'field-two'; await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    route.params.memberId = 'field-three'; await flushPromises()
    expect(mocks.readPinned).toHaveBeenCalledTimes(2)
    mocks.readPinned.mockResolvedValue(page('field-three', 'release-next'))
    route.query = { release_id: 'release-next' }; await flushPromises()
    expect(mocks.readPinned).toHaveBeenCalledTimes(3)
  })
  it('does not let an old release response replace the newer directory', async () => {
    let finishOld!: (value: unknown) => void
    mocks.readPinned.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
    const next = page('field-one', 'release-next')
    mocks.readPinned.mockResolvedValueOnce(next)
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises()
    route.query = { release_id: 'release-next' }; await flushPromises()
    finishOld(page()); await flushPromises()
    mocks.readBatch.mockResolvedValue({ ...page('field-two', 'release-next'), directory: next.directory })
    route.params.memberId = 'field-two'; await flushPromises()
    expect(mocks.readBatch).toHaveBeenCalledWith(next.directory, 'field-two', expect.anything())
    expect(wrapper.text()).toContain('field-two')
  })
})
