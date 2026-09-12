// @vitest-environment happy-dom
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import ConceptPage from './ConceptFreeWiki830G2.vue'
enableAutoUnmount(afterEach)

const mocks = vi.hoisted(() => ({ read: vi.fn(), get: vi.fn(), loadPreparation: vi.fn(), loadActive: vi.fn(), readBatch: vi.fn() }))
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
    mocks.readBatch.mockResolvedValue({ readMode: 'active', directory: active, member: field, relatedMembers: [],
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
