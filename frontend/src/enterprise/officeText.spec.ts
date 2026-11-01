// S11h acceptance (protected, written by Claude): when the preview fails, the text view reads the
// cited slide, body block or sheet row from the downloaded file the way the platform captured it
// (internal/sourceloc/office.go) and marks the quote, ignoring whitespace
// (Spec docs/design/slices/S11h-Office渲染失败时的文本视图.md §2.2).
import { describe, expect, it } from 'vitest'
import { officeTarget } from './officeCitation'
import { OfficePackageRejected } from './officePackage'
import { readOfficeText, type OfficeText } from './officeText'
import { deck, group, manual, tableFrame, textBox, workbook, wp, wtable } from './__tests__/officeTextFixtures'

const slide = (n: number, quote = '') => officeTarget({ kind: 'PPTX_SHAPE', slide: n }, quote)!
const block = (index: number, quote = '') => officeTarget({ kind: 'DOCX_BLOCK', block_index: index }, quote)!
const row = (sheet: string, r: number, quote = '') =>
  officeTarget({ kind: 'XLSX_CELL_RANGE', sheet, cell_range: `A${r}:XFD${r}` }, quote)!

const text = (line: OfficeText['lines'][number]) => line.segments.map(segment => segment.text).join('')
const lines = (view: OfficeText) => view.lines.map(line => [line.kind, text(line), line.cited])
const marked = (view: OfficeText) =>
  view.lines.flatMap(line => line.segments.filter(segment => segment.mark).map(segment => segment.text))

// Stored as slide1..slide3 but presented in the order slide3, slide2, slide1.
const DECK = () => deck([
  { shapes: textBox(2, ['第三张', '保费 &amp; 保额']) },
  {
    shapes: textBox(2, ['标题甲', '犹豫期为\n十五日', ''])
      + group(3, tableFrame(4, [['项目', '说明'], ['犹豫期', '十五日']]) + textBox(5, ['组合里的文字'])),
    notes: ['备注第一段'],
  },
  { shapes: textBox(2, ['第一张']) },
], { order: [2, 1, 0] })

describe('pptx text view', () => {
  it('lists the paragraphs of the cited slide in presentation order, then its notes', async () => {
    const view = await readOfficeText(await DECK(), slide(2, '犹豫期为 十五日'))
    expect(lines(view)).toEqual([
      ['paragraph', '标题甲', true],
      ['paragraph', '犹豫期为 十五日', true],
      ['paragraph', '项目', true],
      ['paragraph', '说明', true],
      ['paragraph', '犹豫期', true],
      ['paragraph', '十五日', true],
      ['paragraph', '组合里的文字', true],
      ['note', '备注第一段', true],
    ])
    expect(view.quoted).toBe(true)
    expect(marked(view)).toEqual(['犹豫期为 十五日'])
  })

  it.each([
    [1, ['第一张']],
    [3, ['第三张', '保费 & 保额']],
  ])('finds slide %i by its place in the presentation', async (n, expected) => {
    const view = await readOfficeText(await DECK(), slide(n))
    expect(view.lines.map(text)).toEqual(expected)
  })

  it('marks a quote that runs across paragraphs or into the notes', async () => {
    expect(marked(await readOfficeText(await DECK(), slide(2, '标题甲犹豫期为')))).toEqual(['标题甲', '犹豫期为'])
    expect(marked(await readOfficeText(await DECK(), slide(2, '组合里的文字 备注')))).toEqual(['组合里的文字', '备注'])
  })

  it('keeps the slide but marks nothing when the quote is not there word for word', async () => {
    const view = await readOfficeText(await DECK(), slide(2, '犹豫期为二十日'))
    expect(view.quoted).toBe(false)
    expect(marked(view)).toEqual([])
    expect(view.lines).toHaveLength(8)
  })

  it('has no lines for a slide the deck does not have', async () => {
    expect((await readOfficeText(await DECK(), slide(4, '第一张'))).lines).toEqual([])
  })

  it('refuses a file that is not a readable package', async () => {
    await expect(readOfficeText(new Uint8Array([1, 2, 3]).buffer, slide(1))).rejects.toBeInstanceOf(OfficePackageRejected)
  })
})

// Body blocks: 1 paragraph, 2 a content control (transparent), 3 empty, 4 a table (one line per
// row), 5 a paragraph with deleted text and a tab, 6–8 paragraphs.
const MANUAL = () => manual([
  wp('第一段'),
  `<w:sdt><w:sdtPr><w:alias w:val="控件"/><w:t>控件属性</w:t></w:sdtPr><w:sdtContent>${wp('控件里的段落')}</w:sdtContent></w:sdt>`,
  '<w:p/>',
  wtable([['项目', '说明'], ['等待期', '九十日']]),
  '<w:p><w:r><w:t xml:space="preserve">等待期为</w:t></w:r><w:del><w:r><w:delText>三十日</w:delText></w:r></w:del>'
    + '<w:r><w:tab/><w:t>九十日</w:t></w:r></w:p>',
  wp('第六段'), wp('第七段'), wp('第八段'),
].join(''))

describe('docx text view', () => {
  it('shows the cited block with two blocks on either side, numbered as the platform numbers them', async () => {
    const view = await readOfficeText(await MANUAL(), block(3, '九十日'))
    expect(lines(view)).toEqual([
      ['block', '控件里的段落', false],
      ['block', '项目 说明', true],
      ['block', '等待期 九十日', true],
      ['block', '等待期为 九十日', false],
      ['block', '第六段', false],
    ])
    // The quote also occurs in block 5; only the cited block is searched.
    expect(view.lines.map(line => line.segments.some(segment => segment.mark))).toEqual([false, false, true, false, false])
  })

  it('counts block_index from 0', async () => {
    expect(lines(await readOfficeText(await MANUAL(), block(0)))).toEqual([
      ['block', '第一段', true],
      ['block', '控件里的段落', false],
    ])
  })

  it('has no lines when the cited block has no text', async () => {
    expect((await readOfficeText(await MANUAL(), block(2))).lines).toEqual([])
    expect((await readOfficeText(await MANUAL(), block(20))).lines).toEqual([])
  })
})

const RATES = () => workbook({
  Notes: { 1: ['说明', '取值'], 3: ['示例', '180 元'] },
  'R&amp;D': { 1: ['只有一行'] },
  Rates: { 1: ['年龄', '年保费', { inline: '备注' }], 2: ['18-30', 120], 3: ['31-40', 180, { inline: '含 税' }] },
})

describe('xlsx text view', () => {
  it('shows the cited row of the named sheet under its first row', async () => {
    const view = await readOfficeText(await RATES(), row('Rates', 3, '31-40\t180'))
    expect(view.lines.map(line => [line.kind, line.column, text(line), line.cited])).toEqual([
      ['header', 'A', '年龄', false],
      ['header', 'B', '年保费', false],
      ['header', 'C', '备注', false],
      ['cell', 'A', '31-40', true],
      ['cell', 'B', '180', true],
      ['cell', 'C', '含 税', true],
    ])
    expect(marked(view)).toEqual(['31-40', '180'])
  })

  it('shows no header for the first row, and decodes sheet names', async () => {
    expect(lines(await readOfficeText(await RATES(), row('R&D', 1)))).toEqual([['cell', '只有一行', true]])
  })

  it('has no lines for a row or sheet without cells', async () => {
    expect((await readOfficeText(await RATES(), row('Rates', 9))).lines).toEqual([])
    expect((await readOfficeText(await RATES(), row('Missing', 1))).lines).toEqual([])
  })
})
