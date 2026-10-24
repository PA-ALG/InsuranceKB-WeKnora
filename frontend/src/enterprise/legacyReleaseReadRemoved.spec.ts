// S7d-2c-3d-2 acceptance (protected, written by Claude): the chat drawer no longer reads pinned
// releases through the retired release-scope API, and the Schema Wiki strings S7b left behind are
// gone (Spec docs/design/slices/S7d-2c-3d-2-删除前端固定版本读取.md §3).
import { describe, expect, it } from 'vitest'
import wikiApiSource from '@/api/wiki/index.ts?raw'
import agentStreamSource from '@/views/chat/components/AgentStreamDisplay.vue?raw'
import zhCN from '@/i18n/locales/zh-CN.ts?raw'
import enUS from '@/i18n/locales/en-US.ts?raw'
import jaJP from '@/i18n/locales/ja-JP.ts?raw'
import koKR from '@/i18n/locales/ko-KR.ts?raw'
import ruRU from '@/i18n/locales/ru-RU.ts?raw'

const locales = { zhCN, enUS, jaJP, koKR, ruRU }
const deadKeys = [
  'tabSchemaWiki', 'schemaLoading', 'schemaNotCompiled', 'schemaLoadFailed', 'schemaUnknown',
  'schemaUndetermined', 'schemaPresent', 'schemaAbsent', 'schemaCitation', 'schemaCitationUnavailable',
]
const key = (name: string) => new RegExp(`^\\s*["']?${name}["']?\\s*:`, 'm')

describe('the pinned release read path', () => {
  it('leaves the wiki API without release-scope reads', () => {
    for (const name of ['release-scopes', 'getReleaseWikiPage', 'WikiReleaseAuthority']) {
      expect(wikiApiSource).not.toContain(name)
    }
  })

  it('leaves the chat drawer without release authorities', () => {
    for (const name of ['wikiDrawerAuthority', 'resolveReleaseCitationKb', 'resolveWikiReleaseAuthority']) {
      expect(agentStreamSource).not.toContain(name)
    }
  })
})

describe('the Schema Wiki strings', () => {
  it.each(Object.entries(locales))('are gone from %s', (_, source) => {
    expect(deadKeys.filter(name => key(name).test(source))).toEqual([])
  })

  it.each(Object.entries(locales))('keep the enterprise navigation label in %s', (_, source) => {
    expect(source).toMatch(key('schemaWiki'))
  })
})
