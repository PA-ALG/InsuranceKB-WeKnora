// @vitest-environment happy-dom
// U-5a acceptance (protected, written by Claude): the enterprise pages, sidebar entry and UI strings
// the app sees stay the same when they move out of upstream's route table, menu store and i18n setup
// (Spec docs/design/slices/U-5a-前端企业入口收口.md §3).
import { beforeEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import router from '@/router'
import i18n from '@/i18n'
import { useMenuStore } from '@/stores/menu'
import enUS from '@/i18n/locales/en-US.ts'
import jaJP from '@/i18n/locales/ja-JP.ts'
import koKR from '@/i18n/locales/ko-KR.ts'
import ruRU from '@/i18n/locales/ru-RU.ts'
import zhCN from '@/i18n/locales/zh-CN.ts'
import zhTW from '@/i18n/locales/zh-TW.ts'
import { withEnterpriseMessages } from './i18n/index.ts'
import enterpriseEnUS from './i18n/messages/en-US.ts'
import enterpriseZhCN from './i18n/messages/zh-CN.ts'

// Taken before anything is assembled, so the expectation never sees a bundle the app merged into.
const EXPECTED_MESSAGES = withEnterpriseMessages(structuredClone({
  'en-US': enUS, 'ja-JP': jaJP, 'ko-KR': koKR, 'ru-RU': ruRU, 'zh-CN': zhCN, 'zh-TW': zhTW,
}))

// The router, i18n instance and sidebar menu as the running app sees them.
function assemble() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return { menu: useMenuStore(pinia) }
}

type Props = Record<string, string | undefined>
const ROUTES: [name: string, path: string, url: string, props: Props | false][] = [
  ['enterpriseSpaces', '/platform/enterprise', '/platform/enterprise', false],
  ['enterpriseSpace', '/platform/enterprise/:spaceId', '/platform/enterprise/s1', { spaceId: 's1', releaseId: 'r1' }],
  ['enterpriseChanges', '/platform/enterprise/:spaceId/changes', '/platform/enterprise/s1/changes',
    { spaceId: 's1', releaseId: 'r1' }],
  ['enterpriseSpotChecks', '/platform/enterprise/:spaceId/spot-checks', '/platform/enterprise/s1/spot-checks',
    { spaceId: 's1' }],
  ['enterpriseReviews', '/platform/enterprise/:spaceId/reviews', '/platform/enterprise/s1/reviews', { spaceId: 's1' }],
  ['enterpriseConfirmations', '/platform/enterprise/:spaceId/confirmations', '/platform/enterprise/s1/confirmations',
    { spaceId: 's1' }],
  ['enterpriseGraph', '/platform/enterprise/:spaceId/graph', '/platform/enterprise/s1/graph',
    { spaceId: 's1', releaseId: 'r1' }],
  ['enterpriseConcept', '/platform/enterprise/:spaceId/concepts/:conceptKey', '/platform/enterprise/s1/concepts/c1',
    { spaceId: 's1', conceptKey: 'c1', releaseId: 'r1' }],
  ['enterpriseWikiPage', '/platform/enterprise/:spaceId/wiki/:entityId/:pageType/:pageSlug',
    '/platform/enterprise/s1/wiki/e1/entity/p1',
    { spaceId: 's1', entityId: 'e1', pageType: 'entity', pageSlug: 'p1', releaseId: 'r1' }],
  ['enterpriseEntity', '/platform/enterprise/:spaceId/entities/:entityId', '/platform/enterprise/s1/entities/e1',
    { spaceId: 's1', entityId: 'e1', releaseId: 'r1' }],
]
const COMPONENTS: Record<string, () => Promise<{ default: unknown }>> = {
  enterpriseSpaces: () => import('./EnterpriseSpaces.vue'),
  enterpriseSpace: () => import('./EnterpriseSpace.vue'),
  enterpriseChanges: () => import('./EnterpriseChanges.vue'),
  enterpriseSpotChecks: () => import('./EnterpriseSpotChecks.vue'),
  enterpriseReviews: () => import('./EnterpriseReviews.vue'),
  enterpriseConfirmations: () => import('./EnterpriseConfirmations.vue'),
  enterpriseGraph: () => import('./EnterpriseGraph.vue'),
  enterpriseConcept: () => import('./EnterpriseConcept.vue'),
  enterpriseWikiPage: () => import('./EnterpriseWikiPage.vue'),
  enterpriseEntity: () => import('./EnterpriseEntity.vue'),
}

const leaf = (url: string) => {
  const resolved = router.resolve(url)
  return { resolved, record: resolved.matched[resolved.matched.length - 1] }
}

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
})

describe('the enterprise pages', () => {
  it('are exactly the eleven enterprise routes under the Platform layout', () => {
    assemble()
    const names = router.getRoutes()
      .filter(record => typeof record.name === 'string')
      .filter(record => (record.name as string).startsWith('enterprise') || record.name === 'materialsWiki')
      .map(record => [record.name, record.path])
    expect(names.sort()).toEqual([
      ...ROUTES.map(([name, path]) => [name, path]),
      ['materialsWiki', '/platform/knowledge-bases/:kbId/materials-wiki'],
    ].sort())
    for (const [name, , url] of ROUTES) {
      const { resolved, record } = leaf(url)
      expect(resolved.name).toBe(name)
      expect(resolved.matched.map(match => match.name)).toEqual(['Platform', name])
      expect(record.meta).toEqual({ requiresInit: true, requiresAuth: true })
    }
  })

  it('pass the same props, with a release only when one non-empty value is given', () => {
    assemble()
    for (const [name, , url, expected] of ROUTES) {
      const { record } = leaf(url)
      const props = record.props.default
      if (expected === false) {
        expect(props, name).toBe(false)
        continue
      }
      const call = (query: string) => (props as (route: unknown) => Props)(router.resolve(`${url}${query}`))
      expect(call('?release=r1'), name).toEqual(expected)
      if ('releaseId' in expected) {
        expect(call(''), name).toEqual({ ...expected, releaseId: undefined })
        expect(call('?release='), name).toEqual({ ...expected, releaseId: undefined })
        expect(call('?release=a&release=b'), name).toEqual({ ...expected, releaseId: undefined })
      }
    }
  })

  it('load the enterprise page components lazily', async () => {
    assemble()
    for (const [name, , url] of ROUTES) {
      const load = leaf(url).record.components?.default as () => Promise<{ default: unknown }>
      expect((await load()).default, name).toBe((await COMPONENTS[name]()).default)
    }
  })

  it('keep the old materials-wiki bookmark as a redirect to the materials tab', () => {
    assemble()
    const { resolved, record } = leaf('/platform/knowledge-bases/kb1/materials-wiki?x=1')
    expect(resolved.matched.map(match => match.name)).toEqual(['Platform', 'materialsWiki'])
    expect(record.meta).toEqual({ requiresInit: true, requiresAuth: true })
    expect((record.redirect as (to: unknown) => unknown)(resolved)).toEqual({
      name: 'knowledgeBaseDetail', params: { kbId: 'kb1' }, query: { x: '1', tab: 'materials' },
    })
  })
})

describe('the enterprise UI strings', () => {
  it('are merged into every upstream locale exactly as before', () => {
    assemble()
    expect([...i18n.global.availableLocales].sort()).toEqual(Object.keys(EXPECTED_MESSAGES).sort())
    for (const locale of i18n.global.availableLocales) {
      expect(i18n.global.getLocaleMessage(locale), locale).toEqual(EXPECTED_MESSAGES[locale as 'zh-CN'])
    }
  })
})

describe('the sidebar', () => {
  it('lists one enterprise entry right after the knowledge bases', () => {
    const { menu } = assemble()
    const paths = menu.menuArr.map(item => item.path)
    expect(paths.filter(path => path === 'enterprise')).toHaveLength(1)
    expect(paths.indexOf('enterprise')).toBe(paths.indexOf('knowledge-bases') + 1)
    expect({ ...menu.menuArr[paths.indexOf('enterprise')] }).toEqual({
      title: enterpriseZhCN.menu.enterpriseKnowledge, titleKey: 'menu.enterpriseKnowledge', icon: 'enterprise',
      path: 'enterprise',
    })
  })

  it('retitles the entry when the language changes', async () => {
    const { menu } = assemble()
    const entry = () => menu.menuArr.find(item => item.path === 'enterprise')
    i18n.global.locale.value = 'en-US'
    await nextTick()
    expect(entry()?.title).toBe(enterpriseEnUS.menu.enterpriseKnowledge)
    i18n.global.locale.value = 'zh-CN'
    await nextTick()
    expect(entry()?.title).toBe(enterpriseZhCN.menu.enterpriseKnowledge)
  })

  it('keeps chat sessions under the new-chat entry', () => {
    const { menu } = assemble()
    menu.updataMenuChildren({ id: 'session-1' })
    expect(menu.menuArr.find(item => item.path === 'creatChat')?.children?.map(child => child.id)).toEqual(['session-1'])
    expect(menu.menuArr.find(item => item.path === 'enterprise')?.children).toBeUndefined()
  })
})
