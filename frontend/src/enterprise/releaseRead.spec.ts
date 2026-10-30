// @vitest-environment happy-dom
import { effectScope, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }))
import { get } from '@/utils/request'
import { useReleaseCustody } from './useReleaseCustody'
import { citesPinnedRelease, useReleaseWikiDrawer } from './useReleaseWikiDrawer'
const scopes: ReturnType<typeof effectScope>[] = []
function scoped<T>(fn: () => T): T { const scope = effectScope(); scopes.push(scope); return scope.run(fn)! }
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(yes => { resolve = yes }); return { promise, resolve }
}
const authority = { wiki_kb_id: 'wiki', space_id: 'space', raw_kb_id: 'raw', release_id: 'release-one' }
const requested = () => vi.mocked(get).mock.calls.map(call => String(call[0]))
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); vi.resetAllMocks() })
describe('release custody', () => {
  it('hides native tabs while loading, then redirects managed graph entry to documents', async () => {
    const response = deferred<any>(); vi.mocked(get).mockReturnValue(response.promise)
    const tab = ref('graph'); const state = scoped(() => useReleaseCustody(ref('wiki'), tab))
    expect(state.nativeWikiAllowed.value).toBe(false)
    response.resolve({ managed: true, kind: 'wiki', state: 'active' }); await nextTick()
    expect(state.isManaged.value).toBe(true); expect(state.nativeWikiAllowed.value).toBe(false)
    expect(tab.value).toBe('documents')
    expect(get).toHaveBeenCalledWith('/api/v1/knowledgebase/wiki/release-custody')
  })
  it('keeps managed knowledge bases on documents if a native tab is selected later', async () => {
    vi.mocked(get).mockResolvedValue({ managed: true, kind: 'wiki', state: 'active' } as any)
    const tab = ref('documents'); scoped(() => useReleaseCustody(ref('wiki'), tab)); await nextTick()
    tab.value = 'wiki'; await nextTick(); expect(tab.value).toBe('documents')
    tab.value = 'documents'; await nextTick(); expect(tab.value).toBe('documents')
  })
  it('preserves unmanaged native tabs and rejects stale classifications after navigation', async () => {
    const old = deferred<any>(); const current = deferred<any>()
    vi.mocked(get).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const kb = ref('old'); const tab = ref('wiki'); const state = scoped(() => useReleaseCustody(kb, tab))
    kb.value = 'current'; old.resolve({ managed: false }); await nextTick()
    expect(state.nativeWikiAllowed.value).toBe(false)
    current.resolve({ managed: false, kind: '', state: '' }); await nextTick()
    expect(state.nativeWikiAllowed.value).toBe(true); expect(tab.value).toBe('wiki')
  })
  it('fails closed on errors and malformed classifications and supports retry', async () => {
    vi.mocked(get).mockRejectedValueOnce({ status: 503 }).mockResolvedValueOnce({ managed: 'false' } as any)
      .mockResolvedValueOnce({ managed: false, kind: '', state: '' } as any)
    const state = scoped(() => useReleaseCustody(ref('wiki'), ref('documents'))); await nextTick()
    expect(state.error.value).toBeTruthy(); expect(state.nativeWikiAllowed.value).toBe(false)
    await state.retry(); expect(state.error.value).toBeTruthy(); expect(state.nativeWikiAllowed.value).toBe(false)
    await state.retry(); expect(state.error.value).toBe(''); expect(state.nativeWikiAllowed.value).toBe(true)
  })
})
describe('release wiki citations', () => {
  it('treats a citation the target KB found in an old pinned result as pinned, whatever the authorities hold', () => {
    for (const authorities of [[authority], [], {}, null, undefined]) {
      const events = [{ tool_data: { found_kbs: { slug: ['wiki'] }, release_authorities: authorities } }]
      expect(citesPinnedRelease(events, 'wiki', 'slug')).toBe(true)
    }
    const named = [{ tool_data: { found_kbs: { slug: 'wiki' }, release_authorities: [] } }]
    expect(citesPinnedRelease(named, 'wiki', 'slug')).toBe(true)
  })
  it('lets the latest event that found the slug for the target KB decide', () => {
    const pinned = { tool_data: { found_kbs: { slug: ['wiki'] }, release_authorities: [authority] } }
    const native = { tool_data: { found_kbs: { slug: 'wiki' } } }
    expect(citesPinnedRelease([pinned, native], 'wiki', 'slug')).toBe(false)
    expect(citesPinnedRelease([native, pinned], 'wiki', 'slug')).toBe(true)
  })
  it('does not let a newer result for another KB clear an old pin (review R1)', () => {
    const pinned = { type: 'tool_call', tool_data: { found_kbs: { slug: ['legacy-kb'] },
      release_authorities: [{ ...authority, wiki_kb_id: 'legacy-kb', release_id: 'historic' }] } }
    const other = { type: 'tool_call', tool_data: { found_kbs: { slug: ['native-kb'] } } }
    expect(citesPinnedRelease([pinned, other], 'legacy-kb', 'slug')).toBe(true)
    expect(citesPinnedRelease([pinned, other], 'native-kb', 'slug')).toBe(false)
    const empty = { type: 'tool_call', tool_data: { found_kbs: { slug: null } } }
    expect(citesPinnedRelease([pinned, empty], 'legacy-kb', 'slug')).toBe(true)
  })
  it('skips uninterpretable events instead of throwing (review R2)', () => {
    const pinned = { tool_data: { found_kbs: { slug: ['legacy-kb'] }, release_authorities: [] } }
    const noise: any[] = [null, 'event', 7, { tool_data: null }, { tool_data: { found_kbs: null } }, { tool_data: 'x' }]
    expect(citesPinnedRelease([pinned, ...noise] as any, 'legacy-kb', 'slug')).toBe(true)
    expect(citesPinnedRelease(noise as any, 'legacy-kb', 'slug')).toBe(false)
  })
  it('refuses a citation no event found for the target KB when the session holds pinned results', () => {
    const pinned = { tool_data: { found_kbs: { other: ['wiki'] }, release_authorities: [authority] } }
    expect(citesPinnedRelease([pinned], 'wiki', 'slug')).toBe(true)
    expect(citesPinnedRelease([{ tool_data: { found_kbs: { other: ['wiki'] } } }], 'wiki', 'slug')).toBe(false)
    expect(citesPinnedRelease([], 'wiki', 'slug')).toBe(false)
  })
  it('reads native pages and keeps the KB through internal links', async () => {
    vi.mocked(get).mockResolvedValue({ data: { slug: 'slug', page_type: 'concept', title: 'Native', content: '[[next]]' } } as any)
    const drawer = scoped(() => useReleaseWikiDrawer()); await drawer.open('wiki', 'slug')
    expect(drawer.page.value).toMatchObject({ slug: 'slug', page_type: 'concept', title: 'Native' })
    await drawer.follow('next')
    expect(requested()).toEqual(['/api/v1/knowledgebase/wiki/wiki/pages/slug', '/api/v1/knowledgebase/wiki/wiki/pages/next'])
  })
  it('prevents older responses overwriting a later citation', async () => {
    const first = deferred<any>(); const second = deferred<any>()
    vi.mocked(get).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const drawer = scoped(() => useReleaseWikiDrawer())
    const pending = drawer.open('wiki', 'old'); const latest = drawer.open('native', 'new')
    second.resolve({ data: { slug: 'new', title: 'New', content: '' } }); await latest
    first.resolve({ data: { slug: 'old', title: 'Old', content: '' } }); await pending
    expect(drawer.page.value?.title).toBe('New')
    expect(get).toHaveBeenLastCalledWith('/api/v1/knowledgebase/native/wiki/pages/new')
  })
  it.each([404, 409, 503])('clears previous content on a %s failure and allows retry', async (status) => {
    vi.mocked(get).mockResolvedValueOnce({ data: { slug: 'first', title: 'First', content: '' } } as any)
      .mockRejectedValueOnce({ status }).mockResolvedValueOnce({ data: { slug: 'next', title: 'Next', content: '' } } as any)
    const drawer = scoped(() => useReleaseWikiDrawer()); await drawer.open('wiki', 'first')
    await drawer.follow('next'); expect(drawer.page.value).toBeNull()
    expect(drawer.error.value).toBe('引用内容加载失败，请重试'); expect(drawer.visible.value).toBe(true)
    await drawer.retry(); expect(drawer.page.value?.title).toBe('Next')
    expect(requested().filter(url => url.includes('release-scopes'))).toEqual([])
  })
})
