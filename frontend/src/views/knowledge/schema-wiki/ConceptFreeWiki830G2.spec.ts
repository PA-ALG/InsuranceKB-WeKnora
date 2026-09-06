// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import ConceptPage from './ConceptFreeWiki830G2.vue'

const mocks = vi.hoisted(() => ({ read: vi.fn(), get: vi.fn() }))
const route = reactive({ params: { kbId: 'wiki-a', memberId: 'concept-a' }, query: {} as Record<string, unknown> })
vi.mock('vue-router', () => ({ useRoute: () => route }))
vi.mock('@/utils/request', () => ({ get: mocks.get }))
vi.mock('@/api/schema-wiki/conceptFreeWiki830G2', () => ({
  readConceptPage830G2: mocks.read, conceptCitationTransport830G2: (_session: unknown, io: any) => ({ getAuthority: io.get, getBytesByToken: io.getBytes }),
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
beforeEach(() => { mocks.read.mockReset(); route.query = {}; mocks.read.mockResolvedValue(response()) })
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
  it('allows a verified source taking 35 seconds while preserving binary response handling', async () => {
    mocks.get.mockImplementation((_path: string, config?: any) => {
      if ((config?.timeout ?? 30000) < 35000) return Promise.reject(new Error('timeout'));
      return Promise.resolve(config?.responseType === 'arraybuffer' ? new Uint8Array([37,80,68,70]).buffer : { verified: true });
    });
    const wrapper = mount(ConceptPage, { global: { stubs } }); await flushPromises();
    await wrapper.get('[data-testid="g2-source"]').trigger('click');
    const io = wrapper.findComponent(stubs.ConceptCitationViewer830G2).props('previewTransport') as any;
    await expect(io.getAuthority('/authority')).resolves.toEqual({ verified: true });
    await expect(io.getBytesByToken('/content')).resolves.toEqual(new Uint8Array([37,80,68,70]));
    const calls = mocks.get.mock.calls.slice(-2);
    expect(calls.every((call: any[]) => call[1].timeout > 35000 && call[1].timeout <= 60000)).toBe(true);
    mocks.get.mockClear(); mocks.get.mockRejectedValue(new Error('source unavailable'));
    await expect(io.getAuthority('/authority')).rejects.toThrow('source unavailable');
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });
});
