// @vitest-environment happy-dom
import { effectScope, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }))
import { get } from '@/utils/request'
import { useReleaseCustody } from './useReleaseCustody'
import { getReleaseWikiPage } from '@/api/wiki'
import { resolveReleaseCitationKb, resolveWikiReleaseAuthority, useReleaseWikiDrawer } from './useReleaseWikiDrawer'
const scopes: ReturnType<typeof effectScope>[] = []
function scoped<T>(fn: () => T): T { const scope = effectScope(); scopes.push(scope); return scope.run(fn)! }
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(yes => { resolve = yes }); return { promise, resolve }
}
const authority = { wiki_kb_id: 'wiki', space_id: 'space', raw_kb_id: 'raw', release_id: 'release-one' }
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); vi.resetAllMocks() })
describe('release custody', () => {
  it('hides native tabs while loading, then redirects managed graph entry to Schema Wiki', async () => {
    const response = deferred<any>(); vi.mocked(get).mockReturnValue(response.promise)
    const tab = ref('graph'); const state = scoped(() => useReleaseCustody(ref('wiki'), tab))
    expect(state.nativeWikiAllowed.value).toBe(false)
    response.resolve({ managed: true, kind: 'wiki', state: 'active' }); await nextTick()
    expect(state.isManaged.value).toBe(true); expect(state.nativeWikiAllowed.value).toBe(false)
    expect(tab.value).toBe('schema')
    expect(get).toHaveBeenCalledWith('/api/v1/knowledgebase/wiki/release-custody')
  })
  it('keeps managed knowledge bases on Schema Wiki if a native tab is selected later', async () => {
    vi.mocked(get).mockResolvedValue({ managed: true, kind: 'wiki', state: 'active' } as any)
    const tab = ref('schema'); scoped(() => useReleaseCustody(ref('wiki'), tab)); await nextTick()
    tab.value = 'materials'; await nextTick(); expect(tab.value).toBe('schema')
    tab.value = 'documents'; await nextTick(); expect(tab.value).toBe('documents')
  })
  it('preserves unmanaged native tabs and rejects stale classifications after navigation', async () => {
    const old = deferred<any>(); const current = deferred<any>()
    vi.mocked(get).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const kb = ref('old'); const tab = ref('materials'); const state = scoped(() => useReleaseCustody(kb, tab))
    kb.value = 'current'; old.resolve({ managed: false }); await nextTick()
    expect(state.nativeWikiAllowed.value).toBe(false)
    current.resolve({ managed: false, kind: '', state: '' }); await nextTick()
    expect(state.nativeWikiAllowed.value).toBe(true); expect(tab.value).toBe('materials')
  })
  it('fails closed on errors and malformed classifications and supports retry', async () => {
    vi.mocked(get).mockRejectedValueOnce({ status: 503 }).mockResolvedValueOnce({ managed: 'false' } as any)
      .mockResolvedValueOnce({ managed: false, kind: '', state: '' } as any)
    const state = scoped(() => useReleaseCustody(ref('wiki'), ref('schema'))); await nextTick()
    expect(state.error.value).toBeTruthy(); expect(state.nativeWikiAllowed.value).toBe(false)
    await state.retry(); expect(state.error.value).toBeTruthy(); expect(state.nativeWikiAllowed.value).toBe(false)
    await state.retry(); expect(state.error.value).toBe(''); expect(state.nativeWikiAllowed.value).toBe(true)
  })
})
describe('release wiki citations', () => {
  it('encodes scope and logical slug in the release read URL', async () => {
    vi.mocked(get).mockResolvedValue({} as any)
    await getReleaseWikiPage({ ...authority, space_id: 'space ?' }, 'concept:保障')
    expect(get).toHaveBeenCalledWith('/api/v1/knowledgebase/wiki/wiki/release-scopes/space%20%3F/raw/raw/releases/release-one/pages/concept%3A%E4%BF%9D%E9%9A%9C')
  })
  it('uses the KB from the release citation even when the surrounding route names another KB', () => {
    const events = [{ tool_data: { found_kbs: { slug: ['managed', 'native'] },
      release_authorities: [{ ...authority, wiki_kb_id: 'managed' }] } }]
    expect(resolveReleaseCitationKb(events, 'slug')).toBe('managed')
    expect(resolveReleaseCitationKb(events, 'unrelated')).toBe('')
  })
  it('does not relabel a native result when a managed KB shares the same slug', () => {
    const events = [{ tool_data: { found_kbs: { slug: ['native', 'wiki'] }, release_authorities: [authority] } }]
    expect(resolveReleaseCitationKb(events, 'slug')).toBe('')
  })
  it('does not substitute an older release result for the latest native result', () => {
    const events = [
      { tool_data: { found_kbs: { slug: ['wiki'] }, release_authorities: [authority] } },
      { tool_data: { found_kbs: { slug: ['native'] } } },
    ]
    expect(resolveReleaseCitationKb(events, 'slug')).toBe('')
  })
  it('resolves no pin when the latest citation-producing event is native', () => {
    const events = [
      { tool_data: { found_kbs: { slug: ['wiki'] }, release_authorities: [authority] } },
      { tool_data: { found_kbs: { slug: ['wiki'] }, release_authorities: [] } },
    ]
    expect(resolveWikiReleaseAuthority(events, 'wiki', 'slug')).toBeNull()
  })
  it('selects the authority for the cited KB from tool results' , () => {
    const events = [{ type: 'tool_call', tool_data: { found_kbs: { slug: ['wiki'] }, release_authorities: [authority] } }]
    expect(resolveWikiReleaseAuthority(events, 'wiki', 'slug')).toEqual(authority)
    expect(resolveWikiReleaseAuthority(events, 'native', 'slug')).toBeNull()
    expect(() => resolveWikiReleaseAuthority([{ tool_data: { release_authorities: [{ wiki_kb_id: 'wiki' }] } }], 'wiki', 'slug')).toThrow()
  })
  it('fails closed when a citation-producing result carries malformed authorities', () => {
    const events = [{ tool_data: { found_kbs: { slug: ['wiki'] }, release_authorities: {} } }]
    expect(() => resolveWikiReleaseAuthority(events, 'wiki', 'slug')).toThrow()
  })
  it('reads published snapshot content and preserves the pin through internal links', async () => {
    vi.mocked(get).mockResolvedValue({ data: { logical_slug: 'slug', kind: 'concept', title: 'Published', content: '[[next]]' } } as any)
    const drawer = scoped(() => useReleaseWikiDrawer()); await drawer.open('wiki', 'slug', authority)
    expect(drawer.page.value).toMatchObject({ slug: 'slug', page_type: 'concept', title: 'Published' })
    await drawer.follow('next')
    expect(get).toHaveBeenLastCalledWith('/api/v1/knowledgebase/wiki/wiki/release-scopes/space/raw/raw/releases/release-one/pages/next')
    expect(drawer.authority.value).toEqual(authority)
  })
  it.each([404, 409])('shows old-version message for %s without native fallback', async (status) => {
    vi.mocked(get).mockRejectedValue({ status })
    const drawer = scoped(() => useReleaseWikiDrawer()); await drawer.open('wiki', 'slug', authority)
    expect(drawer.error.value).toBe('该引用来自旧版本，请重新提问')
    expect(drawer.page.value).toBeNull(); expect(get).toHaveBeenCalledTimes(1); expect(drawer.visible.value).toBe(true)
  })
  it('preserves native reads and prevents older responses overwriting a later citation', async () => {
    const first = deferred<any>(); const second = deferred<any>()
    vi.mocked(get).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const drawer = scoped(() => useReleaseWikiDrawer())
    const pending = drawer.open('wiki', 'old', authority); const latest = drawer.open('native', 'new')
    second.resolve({ data: { slug: 'new', title: 'New', content: '' } }); await latest
    first.resolve({ data: { logical_slug: 'old', title: 'Old', content: '' } }); await pending
    expect(drawer.page.value?.title).toBe('New'); expect(drawer.authority.value).toBeNull()
    expect(get).toHaveBeenLastCalledWith('/api/v1/knowledgebase/native/wiki/pages/new')
  })
  it('clears previous content on failure and allows retry with the same pin', async () => {
    vi.mocked(get).mockResolvedValueOnce({ data: { logical_slug: 'first', kind: 'concept', title: 'First', content: '' } } as any)
      .mockRejectedValueOnce({ status: 503 }).mockResolvedValueOnce({ data: { logical_slug: 'next', kind: 'concept', title: 'Next', content: '' } } as any)
    const drawer = scoped(() => useReleaseWikiDrawer()); await drawer.open('wiki', 'first', authority)
    await drawer.follow('next'); expect(drawer.page.value).toBeNull(); expect(drawer.error.value).toBeTruthy()
    await drawer.retry(); expect(drawer.page.value?.title).toBe('Next')
    expect(get).toHaveBeenLastCalledWith('/api/v1/knowledgebase/wiki/wiki/release-scopes/space/raw/raw/releases/release-one/pages/next')
  })
})
