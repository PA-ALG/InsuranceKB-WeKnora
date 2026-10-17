// S3d-3b acceptance (protected, written by Claude): highlight rectangles in
// normalized_0_1e6_top_left coordinates become CSS percentage boxes
// (Spec docs/design/slices/S3d-3b-原文页查看器.md §3.1).
import { describe, expect, it } from 'vitest'
import { highlightBoxes } from './sourcePage'

describe('highlight boxes', () => {
  it('turns millionths of the page into percentages in input order', () => {
    expect(highlightBoxes([[0, 0, 1_000_000, 1_000_000], [123456, 0, 223456, 10]])).toEqual([
      { left: '0%', top: '0%', width: '100%', height: '100%' },
      { left: '12.3456%', top: '0%', width: '10%', height: '0.001%' },
    ])
  })

  it('clamps to the page and skips empty or malformed rectangles', () => {
    expect(highlightBoxes([
      [-5, -5, 2_000_000, 500_000],
      [10, 10, 10, 20],
      [10, 30, 20, 30],
      [Number.NaN, 0, 5, 5],
      [0, 0, Number.POSITIVE_INFINITY, 5],
    ])).toEqual([{ left: '0%', top: '0%', width: '100%', height: '50%' }])
  })

  it('returns nothing for no rectangles', () => {
    expect(highlightBoxes([])).toEqual([])
  })
})
