// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ConceptDirectory from './ConceptDirectory830G2.vue'

const H = 'a'.repeat(64)
const catalog = {
  mode: 'g2' as const,
  scope: { version: 'schema-wiki-scope.v1' as const, space_id: 'space-a', raw_kb_id: 'raw-a',
    wiki_kb_id: 'wiki-serving', scope_sha256: H },
  releaseID: 'release-a', activationEpoch: 4, candidateHash: H,
  members: [], concepts: [{ kind: 'concept' as const, member_id: `concept_${H}`, revision_id: H,
    member_digest: H, owner_id: 'space-a', title: '被保险人', content: '定义', payload: {} }],
  entities: [
    { entityID: 'entity-a', entityVersion: '596-1', fieldCount: 67, freeItemCount: 0,
      overview: { kind: 'entity_overview' as const, member_id: `entity_overview_${H}`, revision_id: H,
        member_digest: H, owner_id: 'entity-a', title: 'entity-a', content: '', payload: { member_ids: [] } },
      freeWiki: { kind: 'free_wiki' as const, member_id: `free_wiki_${H}`, revision_id: H,
        member_digest: H, owner_id: 'entity-a', title: '开放知识', content: '', payload: { member_ids: [] } } },
  ],
}

describe('ConceptDirectory830G2', () => {
  it('renders pinned concept and entity links through the serving Wiki', () => {
    const wrapper = mount(ConceptDirectory, { props: { catalog }, global: { stubs: { RouterLink: {
      props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>',
    } } } })
    expect(wrapper.text()).toContain('被保险人')
    expect(wrapper.text()).toContain('entity-a')
    expect(wrapper.text()).toContain('67 个字段')
    const targets = wrapper.findAll('a').map(node => JSON.parse(node.attributes('data-to')!))
    expect(targets).toContainEqual({ name: 'conceptPage830G2',
      params: { kbId: 'wiki-serving', memberId: `concept_${H}` }, query: { release_id: 'release-a' } })
    expect(targets).toContainEqual({ name: 'conceptPage830G2',
      params: { kbId: 'wiki-serving', memberId: `entity_overview_${H}` }, query: { release_id: 'release-a' } })
  })
})
