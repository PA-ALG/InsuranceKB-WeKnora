// S3d-4 acceptance (protected, written by Claude): a field value is split into numbered items by
// generic rules — four marker families, a boundary before each marker outside quotes, consecutive
// numbering from 1 — and never loses a character (Spec docs/design/slices/S3d-4-字段取值排版.md §3.1).
import { describe, expect, it } from 'vitest'
import { outlineText, valueOutline, type OutlineItem } from './valueOutline'

const squash = (text: string) => text.replace(/\s+/g, '')

function shape(items: OutlineItem[]): unknown[] {
  return items.map(item => ({ marker: item.marker, lead: item.lead, body: item.body, children: shape(item.children) }))
}

function expectLossless(value: string | string[]) {
  const original = Array.isArray(value) ? value.join('') : value
  expect(squash(outlineText(valueOutline(value)))).toBe(squash(original))
}

describe('numbered items', () => {
  it('splits items written on one line and names each by its leading term', () => {
    const value = '1. 甲责任：给付20%。2. 乙责任：给付50%。'
    const outline = valueOutline(value)
    expect(outline.intro).toBe('')
    expect(shape(outline.items)).toEqual([
      { marker: '1.', lead: '甲责任：', body: '给付20%。', children: [] },
      { marker: '2.', lead: '乙责任：', body: '给付50%。', children: [] },
    ])
    expectLossless(value)
  })

  it('splits items on separate lines and keeps the text before the first item', () => {
    const value = '现金价值规则如下。\n1．定义：指保险单所具有的价值。\n2．查询：可向我们咨询。\n3．退还：30日内退还。'
    const outline = valueOutline(value)
    expect(outline.intro).toBe('现金价值规则如下。')
    expect(outline.items.map(item => item.marker)).toEqual(['1．', '2．', '3．'])
    expect(outline.items.map(item => item.lead)).toEqual(['定义：', '查询：', '退还：'])
    expectLossless(value)
  })

  it('follows numbering past 99', () => {
    const value = Array.from({ length: 120 }, (_, i) => `${i + 1}、病种${i + 1}；`).join('')
    const outline = valueOutline(value)
    expect(outline.items).toHaveLength(120)
    expect(outline.items[119].marker).toBe('120、')
    expect(outline.items[119].body).toBe('病种120；')
  })

  it('accepts a marker after a colon or a semicolon', () => {
    const outline = valueOutline('包括：1. 甲；2. 乙；3. 丙')
    expect(outline.intro).toBe('包括：')
    expect(outline.items.map(item => item.body)).toEqual(['甲；', '乙；', '丙'])
  })
})

describe('nested items', () => {
  it('nests parenthesised items inside a numbered item', () => {
    const value = '1. 条件：满足下列之一：（1）甲；（2）乙。2. 其他：丙。'
    const outline = valueOutline(value)
    expect(shape(outline.items)).toEqual([
      {
        marker: '1.', lead: '条件：', body: '满足下列之一：', children: [
          { marker: '（1）', lead: '', body: '甲；', children: [] },
          { marker: '（2）', lead: '', body: '乙。', children: [] },
        ],
      },
      { marker: '2.', lead: '其他：', body: '丙。', children: [] },
    ])
    expectLossless(value)
  })

  it('splits circled numbers', () => {
    const outline = valueOutline('按下列两者的较大值给付：①基本保险金额；②现金价值。')
    expect(outline.intro).toBe('按下列两者的较大值给付：')
    expect(outline.items.map(item => [item.marker, item.body])).toEqual([['①', '基本保险金额；'], ['②', '现金价值。']])
  })

  it('splits a list whose numbers are followed by a space and a named term', () => {
    const value = '1. 共同标准：须由专科医生明确诊断。2. 轻度疾病释义要点：1 恶性肿瘤——轻度：指甲。2 原位癌：指乙。3 较轻急性心肌梗死：指丙。'
    const outline = valueOutline(value)
    expect(outline.items.map(item => item.lead)).toEqual(['共同标准：', '轻度疾病释义要点：'])
    const diseases = outline.items[1]
    expect(diseases.body).toBe('')
    expect(diseases.children.map(item => [item.marker, item.lead, item.body])).toEqual([
      ['1', '恶性肿瘤——轻度：', '指甲。'],
      ['2', '原位癌：', '指乙。'],
      ['3', '较轻急性心肌梗死：', '指丙。'],
    ])
    expectLossless(value)
  })

  it('nests up to three levels', () => {
    const value = '1. 终止：（1）若未附加，则终止；（2）若附加了，满足以下条件时终止：①甲失效；②乙失效。2. 其他：丙。'
    const outline = valueOutline(value)
    const second = outline.items[0].children[1]
    expect(second.marker).toBe('（2）')
    expect(second.body).toBe('若附加了，满足以下条件时终止：')
    expect(second.children.map(item => item.body)).toEqual(['甲失效；', '乙失效。'])
    expectLossless(value)
  })
})

describe('text that is not a list', () => {
  it.each([
    ['a section reference', '详见7.2及7.3条款。8.1节另有约定。'],
    ['a reference to an item', '发生上述第（1）项或第（2）项情形的，退还现金价值。'],
    ['numbers inside quotes', '合同“1.总则”与“2.释义”所定义的疾病。'],
    ['an enumeration of codes', '形态学编码1、2、3范畴。'],
    ['decimals', '费率为0.09，系数。1.5倍；2.5倍。'],
    ['numbering that does not start at 1', '2. 甲：x。3. 乙：y。'],
    ['numbering with a gap', '1. 甲：x。3. 乙：y。'],
    ['a single item', '1. 甲：x。'],
  ])('keeps %s as plain text', (_, value) => {
    const outline = valueOutline(value)
    expect(outline.items).toEqual([])
    expect(outline.intro).toBe(value)
    expectLossless(value)
  })

  it('names an item only by a short leading term without punctuation', () => {
    const long = '本项责任所称的被保险人因意外伤害或疾病导致身故并经过有关机构依法认定的全部情形之一'
    const outline = valueOutline(`1. ${long}：给付。2. 若满足条件，则给付：x。3. 乙：y。`)
    expect(outline.items.map(item => item.lead)).toEqual(['', '', '乙：'])
    expect(outline.items[0].body).toBe(`${long}：给付。`)
  })
})

describe('review R1–R3 on PR #202: the hierarchy, not only the text, must be right', () => {
  it.each([
    ['a skipped number', '1. 甲：给付。3. 乙：不赔。2. 丙：另有约定。'],
    ['a repeated start', '1. 甲：给付。1. 乙：不赔。2. 丙：另有约定。'],
  ])('does not continue a list across %s', (_, value) => {
    expect(valueOutline(value).items).toEqual([])
    expectLossless(value)
  })

  it('ends a list where the numbering goes wrong instead of skipping over it', () => {
    const value = '1. 甲：a。2. 乙：b。4. 丁：d。3. 丙：c。'
    const outline = valueOutline(value)
    expect(outline.items.map(item => item.marker)).toEqual(['1.', '2.'])
    expect(outline.items[1].body).toBe('b。4. 丁：d。3. 丙：c。')
    expectLossless(value)
  })

  it.each([
    ['curly quotes', '1. 甲：按“1. 甲例；2. 乙例。”办理。2. 乙：另有约定。', '按“1. 甲例；2. 乙例。”办理。'],
    ['corner brackets', '1. 甲：按「1. 甲例；2. 乙例。」办理。2. 乙：另有约定。', '按「1. 甲例；2. 乙例。」办理。'],
    ['title marks', '1. 甲：依据《规则；2. 细则》执行。2. 乙：另有约定。', '依据《规则；2. 细则》执行。'],
  ])('never lifts a number inside %s to the outer list', (_, value, body) => {
    const outline = valueOutline(value)
    expect(outline.items.map(item => item.lead)).toEqual(['甲：', '乙：'])
    expect(outline.items[0].body).toBe(body)
    expect(outline.items[0].children).toEqual([])
    expectLossless(value)
  })

  it.each([
    ['another punctuation', '1. 疾病保障：保障的疾病如下：1、甲病；2、乙病。2. 其他：丙。', ['1、', '2、']],
    ['no space after the number', '1. 退保：需提供：1.保险合同；2.身份证件。2. 现金价值：丁。', ['1.', '2.']],
  ])('takes markers written with %s for a nested level, not for the outer one', (_, value, nested) => {
    const outline = valueOutline(value)
    expect(outline.items.map(item => item.marker)).toEqual(['1.', '2.'])
    expect(outline.items[0].children.map(item => item.marker)).toEqual(nested)
    expectLossless(value)
  })

  it('never takes a colon inside quotes as the end of a spaced number\'s name', () => {
    const value = '1 甲：必须提交：2 份《签收：确认书》原件。2 乙：另有约定。'
    const outline = valueOutline(value)
    expect(outline.items.map(item => item.lead)).toEqual(['甲：', '乙：'])
    expect(outline.items[0].body).toBe('必须提交：2 份《签收：确认书》原件。')
    expect(valueOutline('1 《甲：条款》；2 《乙：条款》。').items).toEqual([])
    expectLossless(value)
  })

  it('keeps markers written in different ways at one level as plain text', () => {
    const value = '现金价值规则如下。\n1．定义：指保险单所具有的价值。\n2、查询：可向我们咨询。\n3. 退还：30日内退还。'
    const outline = valueOutline(value)
    expect(outline.items).toEqual([])
    expect(outline.intro).toBe(value)
  })

  it('keeps the first sub-item when an item starts with its sub-items', () => {
    const value = '1. （1）豁免：甲；（2）给付：乙。2. 其他：丙。'
    const outline = valueOutline(value)
    expect(shape(outline.items)).toEqual([
      {
        marker: '1.', lead: '', body: '', children: [
          { marker: '（1）', lead: '豁免：', body: '甲；', children: [] },
          { marker: '（2）', lead: '给付：', body: '乙。', children: [] },
        ],
      },
      { marker: '2.', lead: '其他：', body: '丙。', children: [] },
    ])
    expectLossless(value)
  })

  it('keeps the first sub-item of a list element that starts with its sub-items', () => {
    const value = ['（1）疾病甲：定义甲；（2）疾病乙：定义乙。', '其他']
    const outline = valueOutline(value)
    expect(outline.items[0].lead).toBe('')
    expect(outline.items[0].children.map(item => item.lead)).toEqual(['疾病甲：', '疾病乙：'])
    expectLossless(value)
  })

  it('never names an item by a parenthesised or circled number', () => {
    const outline = valueOutline('1. （1）豁免：甲。2. ①给付：乙。')
    expect(outline.items.map(item => item.lead)).toEqual(['', ''])
    expect(outline.items.map(item => item.body)).toEqual(['（1）豁免：甲。', '①给付：乙。'])
  })

  it('still names an item that starts with a number of years', () => {
    const outline = valueOutline('1. 18 周岁之前身故：给付保费。2. 18 周岁之后身故：给付保额。')
    expect(outline.items.map(item => item.lead)).toEqual(['18 周岁之前身故：', '18 周岁之后身故：'])
  })
})

describe('list values', () => {
  it('makes each element an item without a marker', () => {
    const outline = valueOutline(['年交：每年一次', '月交'])
    expect(shape(outline.items)).toEqual([
      { marker: '', lead: '年交：', body: '每年一次', children: [] },
      { marker: '', lead: '', body: '月交', children: [] },
    ])
    expectLossless(['年交：每年一次', '月交'])
  })

  it('treats a single element as a string', () => {
    const outline = valueOutline(['1. 甲：x。2. 乙：y。'])
    expect(outline.items.map(item => item.marker)).toEqual(['1.', '2.'])
  })
})

it('loses no character of a long value with real structure', () => {
  const disease = (n: number) => `${n} 疾病${n}：指符合条件${n}的状态；须满足（1）甲；（2）乙。`
  const value = [
    '1. 共同标准：本合同中所称“疾病”是指符合定义的疾病。专科医生应满足：（1）资格；（2）执业；（3）职称。',
    `2. 轻度疾病释义要点：${Array.from({ length: 12 }, (_, i) => disease(i + 1)).join('')}`,
    `3. 重大疾病释义要点：${Array.from({ length: 30 }, (_, i) => disease(i + 1)).join('')}`,
    '4. 其他：详见7.2及第（1）项，费率0.09。',
  ].join('\n')
  const outline = valueOutline(value)
  expect(outline.items).toHaveLength(4)
  expect(outline.items[1].children).toHaveLength(12)
  expect(outline.items[2].children).toHaveLength(30)
  expect(outline.items[2].children[29].lead).toBe('疾病30：')
  expectLossless(value)
})
