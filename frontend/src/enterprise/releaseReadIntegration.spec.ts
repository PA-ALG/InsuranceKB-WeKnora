// @vitest-environment happy-dom
import { parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'
import knowledgeBase from '@/views/knowledge/KnowledgeBase.vue?raw'
import agentStream from '@/views/chat/components/AgentStreamDisplay.vue?raw'

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
  it('passes the event authority to the drawer from citation clicks', async () => {
    const pin = { wiki_kb_id: 'wiki', release_id: 'release', space_id: 'space', raw_kb_id: 'raw' }
    const events = [{ tool_data: { release_authorities: [pin] } }]
    const open = vi.fn(); const resolve = vi.fn().mockReturnValue(pin)
    await action(agentStream, 'openWikiDrawer', {
      props: { session: { agentEventStream: events } }, resolveWikiReleaseAuthority: resolve,
      wikiDrawer: { open }, MessagePlugin: { warning: vi.fn() },
    })('wiki', 'slug')
    expect(resolve).toHaveBeenCalledWith(events, 'wiki', 'slug'); expect(open).toHaveBeenCalledWith('wiki', 'slug', pin)
  })
  it('clears a previous drawer when a release authority cannot be resolved', async () => {
    const drawer = { open: vi.fn(), visible: { value: true } }; const warning = vi.fn()
    await action(agentStream, 'openWikiDrawer', {
      props: { session: { agentEventStream: [] } }, resolveWikiReleaseAuthority: () => { throw new Error('invalid') },
      wikiDrawer: drawer, MessagePlugin: { warning },
    })('wiki', 'slug')
    expect(drawer.open).not.toHaveBeenCalled(); expect(drawer.visible.value).toBe(false)
    expect(warning).toHaveBeenCalledWith('该引用来自旧版本，请重新提问')
  })
  it('prefers the release citation KB to a surrounding KB route', () => {
    const events = [{ tool_data: {} }]
    expect(action(agentStream, 'getKbIdForWiki', {
      props: { session: { agentEventStream: events } }, route: { params: { kbId: 'unrelated' } },
      resolveReleaseCitationKb: vi.fn().mockReturnValue('release-wiki'),
    })('slug')).toBe('release-wiki')
  })
  it('retains the existing pin when clicking an internal wiki link', () => {
    const follow = vi.fn(); const link = document.createElement('a')
    link.className = 'citation-wiki'; link.dataset.slug = 'next'
    action(agentStream, 'handleWikiDrawerClick', { wikiDrawer: { follow } })({
      target: link, preventDefault: vi.fn(), stopPropagation: vi.fn(),
    })
    expect(follow).toHaveBeenCalledWith('next')
  })
})
