// S3e-2 acceptance (protected, written by Claude): a concept is a field that two or more entries
// of the release state (present or explicitly absent); its page shows the field definition, the
// related concepts of the same schema category, one row per entry with a live summary, and the
// model summary with its references and a stale flag (Spec §3, §4).
import { describe, expect, it } from 'vitest'
import { conceptKeys, conceptView, liveSummary } from './conceptView'
import { release } from './__tests__/s3eFixtures'

describe('conceptKeys', () => {
  it('lists fields stated by two or more entries, in profile order', () => {
    // waiting_period: one present, one unknown — not a concept.
    expect(conceptKeys(release())).toEqual(['cooling_off_period', 'premium_grace_period'])
  })
})

describe('liveSummary', () => {
  it.each([
    ['present', '自签收之日起15日。', '自签收之日起15日。'],
    ['present', '1. 期间：自签收之日起15日。2. 退费：全额退还。3. 手续：书面申请。4. 其他：无。', '期间；退费；手续…'],
    ['present', '1. 期间：15日。2. 退费：全额退还。', '期间；退费'],
    ['present', '自签收之日起20日，期间解除合同的，退还全部保费；超过犹豫期解除合同的，退还现金价值。', '自签收之日起20日，期间解除合同的，退还全部保费；'],
    ['present', '甲'.repeat(80), `${'甲'.repeat(60)}…`],
    ['present', ['年交', '月交'], '年交；月交'],
    ['absent_explicitly', null, ''],
    ['unknown', null, ''],
  ])('summarises a %s value', (state, value, summary) => {
    expect(liveSummary(state, value as string | string[] | null)).toBe(summary)
  })
})

describe('conceptView', () => {
  it('gathers the definition, related concepts and one row per entry', () => {
    const view = conceptView(release(), 'cooling_off_period')
    expect(view).not.toBeNull()
    expect(view!.title).toBe('犹豫期')
    expect(view!.definition).toBe('投保人收到合同后可解除合同并退还保费的期间。')
    expect(view!.category).toBe('05 合同与交费规则')
    expect(view!.related).toEqual([{ key: 'premium_grace_period', title: '宽限期' }])
    expect(view!.rows.map(row => [row.entityId, row.name, row.group, row.state, row.evidenceCount])).toEqual([
      ['M1', '甲医疗', '医疗险', 'present', 1],
      ['M2', '乙医疗', '医疗险', 'present', 2],
      ['C1', '丙重疾', '重疾险', 'present', 1],
      ['X1', '丁未分组', '', 'unknown', 0],
    ])
    expect(view!.rows[1].summary).toBe('期间；退费；手续…')
  })

  it('carries the model summary with resolved references and no stale flag', () => {
    const summary = conceptView(release(), 'cooling_off_period')!.summary
    expect(summary).not.toBeNull()
    expect(summary!.explanation).toContain('冷静期')
    expect(summary!.statements.map(s => [s.text, s.refs.map(ref => [ref.entityId, ref.name])])).toEqual([
      ['甲医疗与乙医疗的犹豫期为15日。', [['M1', '甲医疗'], ['M2', '乙医疗']]],
      ['丙重疾的犹豫期为20日。', [['C1', '丙重疾']]],
    ])
    expect(summary!.stale).toBe(false)
  })

  it('flags a summary built on claims that have changed since', () => {
    expect(conceptView(release({ changedDigest: true }), 'cooling_off_period')!.summary!.stale).toBe(true)
  })

  it('has no summary without a concept member, and no view for a non-concept', () => {
    expect(conceptView(release({ concept: false }), 'cooling_off_period')!.summary).toBeNull()
    expect(conceptView(release(), 'premium_grace_period')!.summary).toBeNull()
    expect(conceptView(release(), 'waiting_period')).toBeNull()
    expect(conceptView(release(), 'nope')).toBeNull()
  })
})
