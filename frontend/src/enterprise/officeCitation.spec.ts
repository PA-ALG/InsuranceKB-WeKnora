// S11e acceptance (protected, written by Claude): an Office citation's block locator becomes the
// target of upstream's original-file preview, and anything else falls back to the quote alone
// (Spec docs/design/slices/S11e-Office引用查看器.md §3.1).
import { describe, expect, it } from 'vitest'
import { officeLocateRequest, officeTarget } from './officeCitation'

const QUOTE = '保险期间为一年'

describe('office citation target', () => {
  it('opens the cited slide of a deck', () => {
    expect(officeTarget({ kind: 'PPTX_SHAPE', slide: 2 }, QUOTE)).toEqual({
      format: 'pptx',
      position: { kind: 'slide', slide: 2 },
      locator: { type: 'slide', mapping: 'exact', slide: 2, quote: QUOTE },
    })
  })

  it('opens the cited body block of a document, counting from one like the upstream preview', () => {
    expect(officeTarget({ kind: 'DOCX_BLOCK', block_index: 0 }, QUOTE)).toEqual({
      format: 'docx',
      position: { kind: 'block', block: 1 },
      locator: { type: 'docx', mapping: 'exact', block: 1, quote: QUOTE },
    })
    expect(officeTarget({ kind: 'DOCX_BLOCK', block_index: 4 }, QUOTE)?.locator.block).toBe(5)
  })

  it('opens the cited row of a sheet', () => {
    expect(officeTarget({ kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'A3:XFD3' }, QUOTE)).toEqual({
      format: 'xlsx',
      position: { kind: 'row', sheet: 'Rates', row: 3 },
      locator: { type: 'sheet', mapping: 'exact', sheet: 'Rates', row_start: 3, row_end: 3, quote: QUOTE },
    })
    expect(officeTarget({ kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'A1048576:XFD1048576' }, QUOTE)
      ?.position).toEqual({ kind: 'row', sheet: 'Rates', row: 1_048_576 })
  })

  it('ignores keys outside the kind, which the platform has already verified', () => {
    expect(officeTarget({ kind: 'PPTX_SHAPE', slide: 1, shape_id: '7' }, QUOTE)?.position)
      .toEqual({ kind: 'slide', slide: 1 })
  })

  it.each([
    ['no locator', undefined],
    ['null', null],
    ['a string', 'PPTX_SHAPE'],
    ['an array', [{ kind: 'PPTX_SHAPE', slide: 1 }]],
    ['no kind', { slide: 1 }],
    ['a PDF span', { kind: 'PDF_TEXT_SPAN', page: 1 }],
    ['an unknown kind', { kind: 'PPTX_TABLE_CELL', slide: 1 }],
    ['a slide without number', { kind: 'PPTX_SHAPE' }],
    ['slide 0', { kind: 'PPTX_SHAPE', slide: 0 }],
    ['a negative slide', { kind: 'PPTX_SHAPE', slide: -1 }],
    ['a fractional slide', { kind: 'PPTX_SHAPE', slide: 1.5 }],
    ['a slide as text', { kind: 'PPTX_SHAPE', slide: '2' }],
    ['a non-finite slide', { kind: 'PPTX_SHAPE', slide: Number.POSITIVE_INFINITY }],
    ['an unsafe slide', { kind: 'PPTX_SHAPE', slide: 2 ** 53 }],
    ['a block without index', { kind: 'DOCX_BLOCK' }],
    ['a negative block', { kind: 'DOCX_BLOCK', block_index: -1 }],
    ['a fractional block', { kind: 'DOCX_BLOCK', block_index: 0.5 }],
    ['a block as text', { kind: 'DOCX_BLOCK', block_index: '0' }],
    ['a null block', { kind: 'DOCX_BLOCK', block_index: null }],
    ['a row without sheet', { kind: 'XLSX_CELL_RANGE', cell_range: 'A3:XFD3' }],
    ['an empty sheet', { kind: 'XLSX_CELL_RANGE', sheet: '', cell_range: 'A3:XFD3' }],
    ['a numeric sheet', { kind: 'XLSX_CELL_RANGE', sheet: 3, cell_range: 'A3:XFD3' }],
    ['a row without range', { kind: 'XLSX_CELL_RANGE', sheet: 'Rates' }],
    ['a range over two rows', { kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'A3:XFD4' }],
    ['a partial row', { kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'A3:B3' }],
    ['a single cell', { kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'B3' }],
    ['an absolute range', { kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: '$A$3:$XFD$3' }],
    ['row 0', { kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'A0:XFD0' }],
    ['a zero-padded row', { kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'A03:XFD03' }],
    ['a row past the sheet', { kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'A1048577:XFD1048577' }],
    ['a padded range', { kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: ' A3:XFD3' }],
    ['a lower-case range', { kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'a3:xfd3' }],
  ])('has no preview target for %s', (_name, locator) => {
    expect(officeTarget(locator, QUOTE)).toBeNull()
  })
})

describe('office locate request', () => {
  it('asks the preview to reveal the one locator and match the quote', () => {
    const target = officeTarget({ kind: 'PPTX_SHAPE', slide: 2 }, QUOTE)!
    expect(officeLocateRequest(target, 7)).toEqual({ locators: [target.locator], quotes: [QUOTE], token: 7 })
  })

  it('matches no text when the quote is empty', () => {
    const target = officeTarget({ kind: 'DOCX_BLOCK', block_index: 2 }, '')!
    expect(officeLocateRequest(target, 1)).toEqual({ locators: [target.locator], quotes: [], token: 1 })
  })
})
