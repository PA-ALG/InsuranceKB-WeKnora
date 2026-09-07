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

  it('renders G3 products by classification and formal name with Profile order and bounded lineage links', () => {
    const member = (id: string, owner: string, key: string) => ({ kind: 'field_assertion', member_id: id,
      owner_id: owner, title: key, content: '未知：未发现', payload: { field_key: key } })
    const product = (entityID: string, displayName: string, classification: string, count: number) => {
      const fields = Array.from({ length: count }, (_, index) => ({ fieldKey: `field_${index}`,
        shortTitle: index === 0 ? '保障责任' : `字段 ${index + 1}`, memberID: `assertion_${entityID}_${index}` }))
      return { entityID, entityVersion: `${entityID}@v1`, displayName, issuer: '示例保险公司', productCode: `P-${entityID}`,
        primaryClassification: classification, schemaPackID: `pack_${classification}`, schemaVersion: 'v1',
        schemaPackSHA256: H, schemaPackDisplayName: classification === 'medical_insurance' ? '医疗险产品结构' : '意外险产品结构',
        profileID: `profile_${entityID}`, profileVersion: 'v1', profileSHA256: H,
        qualityStatus: 'REGISTERED_NOT_QUALITY_ADMITTED', releaseLane: 'ISOLATED_NOT_FOR_PRODUCTION',
        overview: { kind: 'entity_overview', member_id: `overview_${entityID}`, owner_id: entityID, title: displayName,
          content: '', payload: {} }, freeWiki: { kind: 'free_wiki', member_id: `free_${entityID}`, owner_id: entityID,
          title: '开放知识', content: '', payload: {} }, sections: [
          { sectionKey: 'coverage', displayName: '保障内容', fields: fields.slice(0, 2) },
          { sectionKey: 'eligibility', displayName: '投保条件', fields: fields.slice(2) },
        ], fieldCount: count, freeItemCount: 0 }
    }
    const entities = [
      product('entity-medical-b', '安康医疗险', 'medical_insurance', 67),
      product('entity-accident', '安心意外险', 'accident_insurance', 66),
      product('entity-medical-a', '倍护医疗险', 'medical_insurance', 67),
      product('entity-critical', '长青重疾险', 'critical_illness_insurance', 71),
      product('entity-endowment', '如意两全险', 'endowment_insurance', 71),
    ]
    const g3 = { mode: 'g3-preparation', scope: catalog.scope, preparationID: 'preparation-g3', status: 'READY',
      statusLabel: '已审核但未发布', candidateHash: H, catalog: {}, members: [], entities,
      alignments: [
        { entityID: 'entity-medical-a', entityVersion: 'entity-medical-a@v1', oldFieldKey: 'social_insurance_requirement',
          newFieldKey: 'social_insurance_requirements', oldMemberID: 'old-a', newMemberID: 'assertion-entity-medical-a-0', oldReleaseID: 'release-old' },
        { entityID: 'entity-medical-b', entityVersion: 'entity-medical-b@v1', oldFieldKey: 'social_insurance_requirement',
          newFieldKey: 'social_insurance_requirements', oldMemberID: 'old-b', newMemberID: 'assertion-entity-medical-b-0', oldReleaseID: 'release-old' },
      ] }
    const wrapper = mount(ConceptDirectory, { props: { catalog: g3 as any }, global: { stubs: { RouterLink: {
      props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>',
    } } } })
    expect(wrapper.text()).toContain('已审核但未发布')
    expect(wrapper.text()).toContain('已登记，尚未完成质量验收')
    expect(wrapper.text()).toContain('342 个字段')
    const groupHeadings = wrapper.findAll('section > h3').map(node => node.text())
    expect(groupHeadings.indexOf('意外险')).toBeLessThan(groupHeadings.indexOf('医疗险'))
    const productHeadings = wrapper.findAll('h4').map(node => node.text())
    expect(productHeadings.indexOf('安康医疗险')).toBeLessThan(productHeadings.indexOf('倍护医疗险'))
    expect(wrapper.text().indexOf('保障内容')).toBeLessThan(wrapper.text().indexOf('投保条件'))
    expect(wrapper.text()).toContain('字段名称调整')
    const targets = wrapper.findAll('a').map(node => JSON.parse(node.attributes('data-to')!))
    expect(targets).toContainEqual({ name: 'conceptPage830G2', params: { kbId: 'wiki-serving', memberId: 'old-a' },
      query: { release_id: 'release-old' } })
    expect(targets).toContainEqual({ name: 'conceptPage830G2', params: { kbId: 'wiki-serving',
      memberId: 'assertion-entity-medical-a-0' }, query: { preparation_id: 'preparation-g3' } })
  })
})
