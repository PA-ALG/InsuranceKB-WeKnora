/** Coordinates are millionths of the page, measured from its top-left corner. */
export type NormalizedRect = readonly [number, number, number, number]

export interface HighlightBox {
  left: string
  top: string
  width: string
  height: string
}

export function highlightBoxes(rects: readonly NormalizedRect[]): HighlightBox[] {
  const boxes: HighlightBox[] = []
  for (const rect of rects) {
    if (!rect.every(Number.isFinite)) continue
    const [left, top, right, bottom] = rect.map(value => Math.min(1_000_000, Math.max(0, value)))
    if (right <= left || bottom <= top) continue
    boxes.push({
      left: `${left / 10_000}%`,
      top: `${top / 10_000}%`,
      width: `${(right - left) / 10_000}%`,
      height: `${(bottom - top) / 10_000}%`,
    })
  }
  return boxes
}
