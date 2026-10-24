// @vitest-environment happy-dom
import { parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { effectScope } from 'vue'
import { describe, expect, it, vi } from 'vitest'
vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }))
import { get } from '@/utils/request'
import knowledgeBase from '@/views/knowledge/KnowledgeBase.vue?raw'
import agentStream from '@/views/chat/components/AgentStreamDisplay.vue?raw'
import { citesPinnedRelease, useReleaseWikiDrawer } from './useReleaseWikiDrawer'

// Run the existing SFC event handlers with ports; unrelated editors do not need mounting.
function action(source: string, name: string, ports: Record<string, unknown>): (...args: any[]) => any {
  const script = parse(source).descriptor.scriptSetup!.content
  const ast = ts.createSourceFile('view.ts', script, ts.ScriptTarget.Latest, true)
  let expression: ts.Expression | undefined
  ast.forEachChild(node => {
    if (ts.isVariableStatement(node)) for (const item of node.declarationList.declarations) {
      if (item.name.getText(ast) === name) expression = item.initializer
    }
  })
  expect(expression).toBeDefined()
  const body = ts.transpileModule(`const action = ${expression!.getText(ast)};`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  return new Function(...Object.keys(ports), `${body}; return action`)(...Object.values(ports))
}

describe('release read integration', () => {
  it('never polls native wiki status before custody allows it', async () => {
    const getWikiStats = vi.fn()
    await action(knowledgeBase, 'fetchWikiStatusOnce', {
      kbId: { value: 'managed' }, isWiki: { value: true }, nativeWikiAllowed: { value: false }, getWikiStats,
    })()
    expect(getWikiStats).not.toHaveBeenCalled()
  })
  it('refuses a pinned citation without a request and clears a previous drawer', async () => {
    const events = [{ tool_data: { found_kbs: { slug: ['wiki'] }, release_authorities: [] } }]
    const drawer = { open: vi.fn(), visible: { value: true } }; const warning = vi.fn()
    const pinned = vi.fn().mockReturnValue(true)
    await action(agentStream, 'openWikiDrawer', {
      props: { session: { agentEventStream: events } }, citesPinnedRelease: pinned,
      wikiDrawer: drawer, MessagePlugin: { warning },
    })('wiki', 'slug')
    expect(pinned).toHaveBeenCalledWith(events, 'wiki', 'slug')
    expect(drawer.open).not.toHaveBeenCalled(); expect(drawer.visible.value).toBe(false)
    expect(warning).toHaveBeenCalledWith('该引用来自旧版本，请重新提问')
  })
  it('refuses and clears the drawer when the pinned check itself fails (review R2)', async () => {
    const drawer = { open: vi.fn(), visible: { value: true } }; const warning = vi.fn()
    await action(agentStream, 'openWikiDrawer', {
      props: { session: { agentEventStream: [] } }, citesPinnedRelease: () => { throw new TypeError('malformed') },
      wikiDrawer: drawer, MessagePlugin: { warning },
    })('wiki', 'slug')
    expect(drawer.open).not.toHaveBeenCalled(); expect(drawer.visible.value).toBe(false)
    expect(warning).toHaveBeenCalledWith('该引用来自旧版本，请重新提问')
  })
  it.each([
    ['a route that names the pinned KB while a newer result belongs to another KB', { kbId: 'legacy-kb' },
      { type: 'tool_call', tool_data: { found_kbs: { slug: ['native-kb'] } } }],
    ['no route and a newer result whose hit is null', {},
      { type: 'tool_call', tool_data: { found_kbs: { slug: null } } }],
  ])('sends no request for an old pinned citation with %s (review R1)', async (_, params, newer) => {
    const pinned = { type: 'tool_call', tool_data: { found_kbs: { slug: ['legacy-kb'] },
      release_authorities: [{ wiki_kb_id: 'legacy-kb', space_id: 'space', raw_kb_id: 'raw', release_id: 'historic' }] } }
    const props = { session: { agentEventStream: [pinned, newer] } }
    const kbId = action(agentStream, 'getKbIdForWiki', { props, route: { params } })('slug')
    expect(kbId).toBe('legacy-kb')
    const drawer = { open: vi.fn(), visible: { value: true } }; const warning = vi.fn()
    await action(agentStream, 'openWikiDrawer', {
      props, citesPinnedRelease, wikiDrawer: drawer, MessagePlugin: { warning },
    })(kbId, 'slug')
    expect(drawer.open).not.toHaveBeenCalled(); expect(drawer.visible.value).toBe(false)
    expect(warning).toHaveBeenCalledWith('该引用来自旧版本，请重新提问')
  })
  it.each([
    ['click', null], ['click', undefined], ['click', 'event'], ['click', 7],
    ['Enter', null], ['Enter', undefined], ['Enter', 'event'], ['Enter', 7],
  ])('refuses an old pinned citation from the %s entry when the stream ends with %s (review R2)', async (entry, noise) => {
    vi.mocked(get).mockReset()
    let late!: (value: unknown) => void
    vi.mocked(get).mockResolvedValueOnce({ data: { slug: 'shown', title: 'Shown', content: '' } } as any)
      .mockReturnValueOnce(new Promise(resolve => { late = resolve }) as any)
    const scope = effectScope(); const drawer = scope.run(() => useReleaseWikiDrawer())!
    await drawer.open('native-kb', 'shown'); const inFlight = drawer.open('native-kb', 'pending')
    const pinned = { type: 'tool_call', tool_data: { found_kbs: { slug: ['legacy-kb'] },
      release_authorities: [{ wiki_kb_id: 'legacy-kb', space_id: 'space', raw_kb_id: 'raw', release_id: 'historic' }] } }
    const props = { session: { agentEventStream: [pinned, noise] } }; const warning = vi.fn()
    const getKbIdForWiki = action(agentStream, 'getKbIdForWiki', { props, route: { params: {} } })
    const openWikiDrawer = action(agentStream, 'openWikiDrawer', {
      props, citesPinnedRelease, wikiDrawer: drawer, MessagePlugin: { warning },
    })
    const link = document.createElement('a'); link.className = 'citation-wiki'; link.dataset.slug = 'slug'
    const ports = { getKbIdForWiki, openWikiDrawer, artifactIndexFromEventTarget: () => null,
      MessagePlugin: { warning }, t: (key: string) => key }
    const event = { target: link, key: 'Enter', preventDefault: vi.fn(), stopPropagation: vi.fn() }
    action(agentStream, entry === 'click' ? 'onRootClick' : 'onRootKeydown', ports)(event)
    await Promise.resolve()
    late({ data: { slug: 'pending', title: 'LATE', content: '' } }); await inFlight
    expect(warning).toHaveBeenCalledWith('该引用来自旧版本，请重新提问')
    expect(drawer.visible.value).toBe(false); expect(drawer.page.value).toBeNull()
    expect(drawer.loading.value).toBe(false); expect(get).toHaveBeenCalledTimes(2)
    scope.stop()
  })
  it('opens a current citation in the cited KB', async () => {
    const open = vi.fn(); const warning = vi.fn()
    await action(agentStream, 'openWikiDrawer', {
      props: { session: { agentEventStream: [] } }, citesPinnedRelease: () => false,
      wikiDrawer: { open, visible: { value: false } }, MessagePlugin: { warning },
    })('wiki', 'slug')
    expect(open).toHaveBeenCalledWith('wiki', 'slug'); expect(warning).not.toHaveBeenCalled()
  })
  it('resolves the wiki KB from the route first, as upstream does', () => {
    const events = [{ tool_data: { found_kbs: { slug: ['found'] } } }]
    expect(action(agentStream, 'getKbIdForWiki', {
      props: { session: { agentEventStream: events } }, route: { params: { kbId: 'route' } },
    })('slug')).toBe('route')
  })
  it('follows internal wiki links inside the drawer', () => {
    const follow = vi.fn(); const link = document.createElement('a')
    link.className = 'citation-wiki'; link.dataset.slug = 'next'
    action(agentStream, 'handleWikiDrawerClick', { wikiDrawer: { follow } })({
      target: link, preventDefault: vi.fn(), stopPropagation: vi.fn(),
    })
    expect(follow).toHaveBeenCalledWith('next')
  })
})
