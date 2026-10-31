import type { SourceLocateRequest, SourceLocator } from '@/utils/sourceLocator'

// An Office citation (S11d) carries the captured block's locator instead of page geometry. Upstream's
// original-file preview already reveals a slide, a body block or sheet rows and then matches the
// quote inside them, so a citation only has to name that target (S11e Spec §3.1). The platform has
// verified the locator; this decides where to open and refuses anything it cannot place.

export type OfficeFormat = 'pptx' | 'docx' | 'xlsx'

export type OfficePosition =
  | { kind: 'slide'; slide: number }
  /** 1-based body paragraph or table, the order docx-preview renders them in. */
  | { kind: 'block'; block: number }
  | { kind: 'row'; sheet: string; row: number }

export interface OfficeTarget {
  format: OfficeFormat
  position: OfficePosition
  locator: SourceLocator
}

// S11b captures XLSX rows as `A<r>:XFD<r>`; Excel has at most 1,048,576 rows.
const WHOLE_ROW = /^A([1-9][0-9]{0,6}):XFD\1$/
const LAST_ROW = 1_048_576

function count(value: unknown, min: number): value is number {
  return Number.isSafeInteger(value) && (value as number) >= min
}

export function officeTarget(raw: unknown, quote: string): OfficeTarget | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const locator = raw as Record<string, unknown>
  switch (locator.kind) {
    case 'PPTX_SHAPE': {
      const slide = locator.slide
      if (!count(slide, 1)) return null
      return {
        format: 'pptx',
        position: { kind: 'slide', slide },
        locator: { type: 'slide', mapping: 'exact', slide, quote },
      }
    }
    case 'DOCX_BLOCK': {
      const index = locator.block_index
      if (!count(index, 0)) return null
      // S11b numbers blocks from 0 (upstream's block number − 1); the preview counts from 1.
      const block = index + 1
      return {
        format: 'docx',
        position: { kind: 'block', block },
        locator: { type: 'docx', mapping: 'exact', block, quote },
      }
    }
    case 'XLSX_CELL_RANGE': {
      const { sheet, cell_range: range } = locator
      if (typeof sheet !== 'string' || !sheet || typeof range !== 'string') return null
      const match = WHOLE_ROW.exec(range)
      const row = match ? Number(match[1]) : 0
      if (row < 1 || row > LAST_ROW) return null
      return {
        format: 'xlsx',
        position: { kind: 'row', sheet, row },
        locator: { type: 'sheet', mapping: 'exact', sheet, row_start: row, row_end: row, quote },
      }
    }
    default:
      return null
  }
}

/** A new token on every opening makes the preview locate again even for the same file. */
export function officeLocateRequest(target: OfficeTarget, token: number): SourceLocateRequest {
  return { locators: [target.locator], quotes: target.locator.quote ? [target.locator.quote] : [], token }
}
