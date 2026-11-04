// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import vocabulary from './entityReviewVocabulary.json'
import zhCN from './i18n/messages/zh-CN'
import enUS from './i18n/messages/en-US'
import jaJP from './i18n/messages/ja-JP'
import koKR from './i18n/messages/ko-KR'
import ruRU from './i18n/messages/ru-RU'
import { reviewRows } from './reviewView'
import { pointDetail, pointItem } from './__tests__/reviewPointFixtures'
import type { EntityReview } from './entityReview'
import type { ReleaseMember } from './enterpriseApi'
import ReviewPointCard from './ReviewPointCard.vue'
import { entityReview } from './entityReview'

describe('entity vocabulary and paired profile boundary', () => {
  it('resolves every configured label in every language, without using parent labels for unknown children', () => {
    expect(vocabulary.version).toMatch(/^\d{4}-\d{2}-\d{2}\.\d+$/)
    for (const bundle of [zhCN, enUS, jaJP, koKR, ruRU]) {
      const fields = bundle.enterpriseKnowledge.review.entityFields as Record<string, unknown>
      for (const key of Object.values(vocabulary.fields)) {
        expect(typeof fields[key]).toBe('string')
        expect(String(fields[key]).trim()).not.toBe('')
      }
    }
    expect(Object.hasOwn(vocabulary.fields, '/identifiers/new_field')).toBe(false)
  })

  it('does not borrow an unavailable paired Release profile for the candidate explanation', () => {
    const entity: ReleaseMember = { kind: 'entity', logical_slug: 'entity/E1', member_digest: 'a'.repeat(64), access_scope: 'space',
      payload: { entity_id: 'E1', entity_type: 'method', names: ['合成方法'], identifiers: { notice: 'test' } } }
    const detail = { ...pointDetail(), ...pointItem('c1', { point_count: 1, pending_points: 1 }),
      head_release_id: 'required', bundle_members: [entity], bundle_removals: [], points: [{
        slug: entity.logical_slug, kind: 'member' as const, status: 'pending' as const, decision: null, release_id: null, blocker: '' }] }
    const rows = reviewRows(detail, { id: 'unrelated', epoch: 2, members: [{ ...entity, kind: 'presentation_profile',
      logical_slug: 'profile/other', payload: { entity_types: ['method'], notices: { test: '不得借用' } } }] })
    const projected = rows.get(entity.logical_slug) as { entity: EntityReview }
    expect(projected.entity.beforeKnown).toBe(false)
    expect(projected.entity.fields.find(field => field.path === '/identifiers/notice')?.after).toEqual({ present: true, value: 'test' })
    expect(JSON.stringify(rows.get(entity.logical_slug))).not.toContain('不得借用')
  })

  it('does not describe a nonentity replacement as deletion of the preceding entity', () => {
    const old: ReleaseMember = { kind: 'entity', logical_slug: 'entity/E1', member_digest: 'a'.repeat(64), access_scope: 'space',
      payload: { entity_id: 'E1', names: ['旧实体'] } }
    const next = { ...old, kind: 'navigation', payload: { domains: [] } }
    const release = { id: 'r1', epoch: 1, members: [old] }
    expect(entityReview(old.logical_slug, old, next, true, release, { ...release, members: [next] })).toBeUndefined()
  })

  it('keeps entity identity visible alongside its name after a decision without actions', () => {
    const view = mount(ReviewPointCard, { props: {
      row: { slug: 'entity/E1', title: '同名实体', entity: { name: '同名实体', beforeKnown: true, fields: [] },
        beforeExists: true, before: null, after: null, quotes: [] },
      entry: { point: { slug: 'entity/E1', kind: 'member', status: 'released', decision: null, release_id: 'r2', blocker: '' },
        error: '', result: null }, busy: false, comparable: true, readonly: true,
    }, global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })] } })
    try {
      expect(view.get('h3').text()).toBe('同名实体')
      expect(view.get('[data-entity-identity]').text()).toBe('entity/E1')
      expect(view.find('[data-point-state]').exists()).toBe(true)
      expect(view.find('[data-point-approve]').exists()).toBe(false)
    } finally { view.unmount() }
  })
})
