import { expect, it } from 'vitest'
import { wikiPage, wikiRelease } from './__tests__/wikiFixtures'
import { wikiPages, wikiPageView } from './wikiPagesView'

it('requires kind, exact product prefix, entity membership and Space scope together', () => {
  const data = wikiRelease()
  data.members = [
    { ...wikiPage('M1', 'concept/wrong-kind', '伪页面'), kind: 'entity' },
    wikiPage('M1', 'concept/wrong-ref', '异产品', { entity_refs: ['M2'] }),
    wikiPage('M10', 'concept/wrong-prefix', '近似前缀', { entity_refs: ['M1'] }),
    { ...wikiPage('M1', 'concept/private', '私有'), access_scope: 'private' },
    wikiPage('M2', 'entity/shared', '共享', { entity_refs: ['M1', 'M2'] }),
    wikiPage('M1', 'concept/valid', '有效', { entity_refs: ['M1', 'M2'] }),
  ]
  expect(wikiPages(data, 'M1').map(page => page.key)).toEqual(['concept/valid'])
  expect(wikiPageView(data, 'M1', 'entity/shared')).toBeNull()
  expect(wikiPages(data, 'M2').map(page => page.key)).toEqual(['entity/shared'])
})

it('rejects malformed identities instead of producing links to another member', () => {
  const data = wikiRelease()
  data.members = [
    wikiPage('M1', 'concept/original', '不匹配', { page_key: 'concept/different' }),
    wikiPage('M1', 'concept/wrong-type', '不匹配', { page_type: 'entity' }),
    wikiPage('M1', 'other/page', '未知种类'),
    wikiPage('M1', 'concept/nested/path', '多级路径'),
    wikiPage('M1', 'concept/..', '上级路径'),
  ]
  expect(wikiPages(data, 'M1')).toEqual([])
  expect(wikiPageView(data, 'M1', 'concept/different')).toBeNull()
})

it('preserves aliases, original evidence indexes and input data', () => {
  const data = wikiRelease()
  const member = data.members.find(item => item.logical_slug === 'wiki/M1/concept/deng-dai-qi')!
  member.payload.aliases = ['观察期', '等待期间']
  const evidence = member.payload.evidence as unknown[]
  evidence.splice(0, 0, { quote: '缺少定位', locator: {} })
  const before = structuredClone(data)
  const page = wikiPageView(data, 'M1', 'concept/deng-dai-qi')!
  expect(page.aliases).toEqual(['观察期', '等待期间'])
  expect(page.evidence).toEqual([
    { index: 1, quote: '等待期为90日。', page: 3 },
    { index: 2, quote: '意外无等待期。', page: 5 },
  ])
  expect(data).toEqual(before)
})

it('sorts a second product independently, concepts before entities and titles in Chinese order', () => {
  const data = wikiRelease()
  data.members.push(
    wikiPage('C1', 'entity/bao-zhang', '保障'),
    wikiPage('C1', 'concept/ze-ren', '责任'),
    wikiPage('C1', 'concept/bao-fei', '保费'),
  )
  expect(wikiPages(data, 'C1').map(page => page.title)).toEqual(['保费', '责任', '保障'])
})
