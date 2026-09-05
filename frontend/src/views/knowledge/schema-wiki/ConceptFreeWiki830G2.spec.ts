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
  readConceptPage830G2: mocks.read, conceptCitationTransport830G2: () => ({}),
}))
vi.mock('@/components/schema-wiki/pdfJsPort', () => ({ createPdfJsPort: () => ({}) }))
const stubs = { RouterLink: { props: ['to'], template: '<a :data-target="JSON.stringify(to)"><slot /></a>' },
  SchemaCitationViewer: { props: ['request'], template: '<div data-testid="source-viewer">{{request.release_id}}</div>' },
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
  it('opens the existing source viewer using the release that supplied the page', async () => {
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
