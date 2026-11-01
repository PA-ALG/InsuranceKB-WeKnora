import type { OfficeTarget } from './officeCitation'
import { decodeEntities, readOfficePackage, type OfficeParts } from './officePackage'

// When upstream's preview cannot show an Office citation (S11h Spec §2.2), the cited slide, body
// block or sheet row is shown as text instead, read from the downloaded file the way the platform
// captured it (internal/sourceloc/office.go): every paragraph of the slide and of its notes; the
// body block, with two blocks on either side; the sheet row, under the sheet's first row. The
// quote is marked ignoring whitespace. Everything returned is plain text for interpolation.

export type OfficeFallbackReason = 'failed' | 'stalled' | 'notLocated'

export interface OfficeTextSegment { text: string; mark: boolean }

export interface OfficeTextLine {
  kind: 'paragraph' | 'note' | 'block' | 'header' | 'cell'
  /** The column of a sheet cell, e.g. `B`. */
  column?: string
  /** Whether the line belongs to the cited slide, block or row. */
  cited: boolean
  segments: OfficeTextSegment[]
}

export interface OfficeText {
  lines: OfficeTextLine[]
  /** Whether the quote was found and marked. */
  quoted: boolean
}

type Draft = Omit<OfficeTextLine, 'segments'> & { text: string }

interface Visitor {
  open?(name: string, attributes: string): void
  close?(name: string): void
  text?(value: string): void
}

// Elements by local name, as the platform's decoder reports them; comments, processing
// instructions and doctypes carry no text.
const TOKEN = /<!--[\s\S]*?-->|<\?[\s\S]*?\?>|<!\[CDATA\[([\s\S]*?)\]\]>|<!DOCTYPE[^>]*>|<\/(?:[\w.-]+:)?([\w.-]+)\s*>|<(?:[\w.-]+:)?([\w.-]+)((?:\s+[\w:.-]+\s*=\s*(?:"[^"]*"|'[^']*'))*)\s*(\/?)>|([^<]+)/g
const ATTRIBUTE = /([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g
const BLOCK_CONTEXT = 2

function walk(xml: string, visit: Visitor): void {
  for (const [, data, closing, opening, raw, empty, chars] of xml.matchAll(TOKEN)) {
    if (opening) {
      visit.open?.(opening, raw)
      if (empty) visit.close?.(opening)
    } else if (closing) {
      visit.close?.(closing)
    } else if (chars !== undefined) {
      visit.text?.(decodeEntities(chars))
    } else if (data !== undefined) {
      visit.text?.(data)
    }
  }
}

function attributes(raw: string): Map<string, string> {
  return new Map([...raw.matchAll(ATTRIBUTE)].map(([, key, double, single]) => [key, decodeEntities(double ?? single)]))
}

/** The relationship an element names through its prefixed `id` attribute (`r:id`). */
function relationshipId(raw: string): string | undefined {
  return [...attributes(raw)].find(([key]) => /^[\w.-]+:id$/.test(key))?.[1]
}

/** DrawingML paragraphs (`drawingParagraphs`): `t` is text, `br` a space, empty ones dropped. */
function paragraphs(xml: string): string[] {
  const out: string[] = []
  let text = ''
  let inText = false
  walk(xml, {
    open: name => {
      if (name === 't') inText = true
      else if (name === 'br') text += ' '
    },
    close: name => {
      if (name === 't') {
        inText = false
      } else if (name === 'p') {
        if (text.trim()) out.push(text.trim())
        text = ''
      }
    },
    text: value => { if (inText) text += value },
  })
  return out
}

async function slideLines(parts: OfficeParts, slide: number): Promise<Draft[]> {
  const presentation = await parts.text(parts.main)
  if (presentation === null) return []
  // The n-th `sldId` of the presentation's own slide list (sections keep lists of their own).
  const ids: (string | undefined)[] = []
  const path: string[] = []
  walk(presentation, {
    open: (name, raw) => {
      if (name === 'sldId' && path.length === 2 && path[1] === 'sldIdLst') ids.push(relationshipId(raw))
      path.push(name)
    },
    close: () => { path.pop() },
  })
  const id = ids[slide - 1]
  const link = id === undefined ? undefined : parts.related(parts.main).find(rel => rel.id === id)
  const xml = link ? await parts.text(link.name) : null
  if (!link || xml === null) return []
  const lines: Draft[] = paragraphs(xml).map(text => ({ kind: 'paragraph', cited: true, text }))
  // Speaker notes belong to their slide's locator.
  for (const notes of parts.related(link.name).filter(rel => rel.type.endsWith('/notesSlide'))) {
    const notesXml = await parts.text(notes.name)
    if (notesXml !== null) lines.push(...paragraphs(notesXml).map(text => ({ kind: 'note' as const, cited: true, text })))
  }
  return lines
}

const CONTROLS = new Set(['sdt', 'sdtContent', 'sdtPr', 'sdtEndPr'])

/**
 * The text units of a document body (`docxUnits`): every body-level paragraph or table is one
 * block, numbered from 1; content controls are transparent; a table gives one unit per row.
 */
function bodyUnits(xml: string): { block: number; text: string }[] {
  const units: { block: number; text: string }[] = []
  let inBody = false
  let depth = 0
  let block = 0
  let tables = 0
  let inText = false
  let skip = 0
  let text = ''
  const flush = () => {
    if (text.trim()) units.push({ block, text: text.trim() })
    text = ''
  }
  walk(xml, {
    open: name => {
      if (!inBody) {
        if (name === 'body') inBody = true
        return
      }
      if (CONTROLS.has(name)) {
        if (name === 'sdtPr' || name === 'sdtEndPr') skip++
        return
      }
      depth++
      if (depth === 1 && (name === 'p' || name === 'tbl')) {
        block++
        text = ''
      }
      if (name === 'tbl') tables++
      else if (name === 't') inText = true
      else if (name === 'tab' || name === 'br' || name === 'cr') text += ' '
      else if (name === 'delText' || name === 'instrText') skip++
    },
    close: name => {
      if (!inBody) return
      if (name === 'body') {
        inBody = false
        return
      }
      if (CONTROLS.has(name)) {
        if (name === 'sdtPr' || name === 'sdtEndPr') skip--
        return
      }
      if (name === 't') inText = false
      else if (name === 'delText' || name === 'instrText') skip--
      else if (name === 'tr' && tables === 1) flush()
      else if (name === 'tc') text += ' '
      else if (name === 'tbl') tables--
      if (depth === 1 && name === 'p' && tables === 0) flush()
      depth--
    },
    text: value => { if (inText && skip === 0) text += value },
  })
  return units
}

async function blockLines(parts: OfficeParts, block: number): Promise<Draft[]> {
  const xml = await parts.text(parts.main)
  if (xml === null) return []
  return bodyUnits(xml)
    .filter(unit => Math.abs(unit.block - block) <= BLOCK_CONTEXT)
    .map(unit => ({ kind: 'block', cited: unit.block === block, text: unit.text }))
}

/** Shared strings by index; phonetic runs are not part of a cell's text. */
function sharedStrings(xml: string): string[] {
  const out: string[] = []
  let current: string | null = null
  let phonetic = 0
  let inText = false
  walk(xml, {
    open: name => {
      if (name === 'si') current = ''
      else if (name === 'rPh') phonetic++
      else if (name === 't') inText = phonetic === 0
    },
    close: name => {
      if (name === 'si') {
        out.push(current ?? '')
        current = null
      } else if (name === 'rPh') {
        phonetic--
      } else if (name === 't') {
        inText = false
      }
    },
    text: value => { if (inText && current !== null) current += value },
  })
  return out
}

const columnIndex = (letters: string) => [...letters].reduce((sum, letter) => sum * 26 + letter.charCodeAt(0) - 64, 0)
const columnName = (index: number): string => (index > 26 ? columnName(Math.floor((index - 1) / 26)) : '')
  + String.fromCharCode(65 + ((index - 1) % 26))

/**
 * The non-empty cells of the wanted rows, by row number. Values are shown as stored: shared and
 * inline strings as text, booleans as TRUE/FALSE, numbers without their number format.
 */
function sheetRows(xml: string, wanted: Set<number>, shared: string[]): Map<number, { column: string; text: string }[]> {
  const rows = new Map<number, { column: string; text: string }[]>()
  let row = 0
  let column = 0
  let cell: { type: string; value: string; inline: string } | null = null
  let inValue = false
  let inline = 0
  let phonetic = 0
  let inText = false
  walk(xml, {
    open: (name, raw) => {
      if (name === 'row') {
        row = Number(attributes(raw).get('r')) || row + 1
        column = 0
      } else if (name === 'c') {
        const a = attributes(raw)
        const letters = /^([A-Z]{1,3})[0-9]*$/.exec(a.get('r') ?? '')?.[1]
        column = letters ? columnIndex(letters) : column + 1
        cell = wanted.has(row) ? { type: a.get('t') ?? '', value: '', inline: '' } : null
      } else if (name === 'v') {
        inValue = true
      } else if (name === 'is') {
        inline++
      } else if (name === 'rPh') {
        phonetic++
      } else if (name === 't') {
        inText = inline > 0 && phonetic === 0
      }
    },
    close: name => {
      if (name === 'v') inValue = false
      else if (name === 'is') inline--
      else if (name === 'rPh') phonetic--
      else if (name === 't') inText = false
      else if (name === 'c' && cell) {
        const text = cell.type === 's' ? shared[Number(cell.value)] ?? ''
          : cell.type === 'inlineStr' ? cell.inline
            : cell.type === 'b' ? (cell.value.trim() === '1' ? 'TRUE' : 'FALSE')
              : cell.value
        if (text.trim()) {
          if (!rows.has(row)) rows.set(row, [])
          rows.get(row)!.push({ column: columnName(column), text })
        }
        cell = null
      }
    },
    text: value => {
      if (!cell) return
      if (inValue) cell.value += value
      else if (inText) cell.inline += value
    },
  })
  return rows
}

async function rowLines(parts: OfficeParts, sheet: string, row: number): Promise<Draft[]> {
  const book = await parts.text(parts.main)
  if (book === null) return []
  let id: string | undefined
  walk(book, {
    open: (name, raw) => {
      if (name === 'sheet' && id === undefined && attributes(raw).get('name') === sheet) id = relationshipId(raw)
    },
  })
  const related = parts.related(parts.main)
  const link = id === undefined ? undefined : related.find(rel => rel.id === id)
  const xml = link ? await parts.text(link.name) : null
  if (xml === null) return []
  const strings = related.find(rel => rel.type.endsWith('/sharedStrings'))
  const stringsXml = strings ? await parts.text(strings.name) : null
  const rows = sheetRows(xml, new Set([1, row]), stringsXml === null ? [] : sharedStrings(stringsXml))
  return [
    ...(row === 1 ? [] : (rows.get(1) ?? []).map(cell => ({ kind: 'header' as const, column: cell.column, cited: false, text: cell.text }))),
    ...(rows.get(row) ?? []).map(cell => ({ kind: 'cell' as const, column: cell.column, cited: true, text: cell.text })),
  ]
}

/** Marks the first occurrence of the quote in the cited lines, whitespace ignored on both sides. */
function marked(drafts: Draft[], quote: string): OfficeText {
  const needle = quote.replace(/\s+/g, '')
  const positions: [line: number, at: number][] = []
  let haystack = ''
  drafts.forEach((draft, line) => {
    if (!draft.cited) return
    for (let at = 0; at < draft.text.length; at++) {
      if (/\s/.test(draft.text[at])) continue
      haystack += draft.text[at]
      positions.push([line, at])
    }
  })
  const start = needle ? haystack.indexOf(needle) : -1
  const ranges = new Map<number, [number, number]>()
  if (start >= 0) {
    for (const [line, at] of positions.slice(start, start + needle.length)) {
      ranges.set(line, [ranges.get(line)?.[0] ?? at, at + 1])
    }
  }
  const lines = drafts.map(({ text, ...line }, index) => {
    const range = ranges.get(index)
    const segments = range
      ? [
          { text: text.slice(0, range[0]), mark: false },
          { text: text.slice(range[0], range[1]), mark: true },
          { text: text.slice(range[1]), mark: false },
        ].filter(segment => segment.text)
      : [{ text, mark: false }]
    return { ...line, segments }
  })
  return { lines, quoted: start >= 0 }
}

/**
 * The cited place of an Office file as text. Throws `OfficePackageRejected` when the file is not
 * a readable package; a place without text has no lines.
 */
export async function readOfficeText(original: ArrayBuffer, target: OfficeTarget): Promise<OfficeText> {
  const parts = await readOfficePackage(original, target.format)
  const position = target.position
  const drafts = position.kind === 'slide' ? await slideLines(parts, position.slide)
    : position.kind === 'block' ? await blockLines(parts, position.block)
      : await rowLines(parts, position.sheet, position.row)
  if (!drafts.some(draft => draft.cited)) return { lines: [], quoted: false }
  return marked(drafts, target.locator.quote ?? '')
}
