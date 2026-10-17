// The numbered structure inside a field value, by the generic rules of S3d-4 Spec §3.1. Display
// only: the published value is never changed, and the parts always join back to its full text.

export interface OutlineItem {
  marker: string
  lead: string
  body: string
  children: OutlineItem[]
}

export interface ValueOutline {
  intro: string
  items: OutlineItem[]
}

interface Marker {
  start: number
  end: number
  number: number
  text: string
  style: string
  rank: number
}

interface Family {
  pattern: RegExp
  number: (match: RegExpExecArray) => number
  // Markers of one family written differently ("1. " / "1." / "1、", "（1）" / "(1)") are different
  // styles: one level of a list uses one style, and a nested level may use another of the family.
  style: (match: RegExpExecArray) => string
  // The marker only counts when a short name ending in a colon outside quotes follows it.
  named?: boolean
}

const MAX_DEPTH = 3
const MAX_LEAD = 32
// A marker only opens an item at the start of the text or right after one of these characters,
// so "第（1）项", "“8.轻度疾病释义”" and "编码3、6、9" stay inside the sentence.
const BOUNDARY = new Set(['。', '；', ';', '！', '!', '？', '?', '：', ':', '\n', '\r'])
const SPACE = /[ \t\u00a0\u3000]/
const LEAD_STOP = /[。；;，,！!？?\n\r]/
// A name never starts with a sub-item number: that number opens the next level instead.
const LEAD_START_STOP = /^(?:[（(]\d{1,3}[）)]|[\u2460-\u2473])/
// Nothing inside quotes or title marks is a marker or a name's colon, whatever precedes it.
const OPENING_QUOTES = new Set(['“', '「', '『', '《'])
const CLOSING_QUOTES = new Set(['”', '」', '』', '》'])

const spaced = (match: RegExpExecArray) => (SPACE.test(match[0].slice(-1)) ? ' ' : '')

// Earlier families win a tie at the same position.
const FAMILIES: Family[] = [
  {
    pattern: /(\d{1,3})([.．、])(?!\d)[ \t\u00a0\u3000]*/g,
    number: match => Number(match[1]),
    style: match => match[2] + spaced(match),
  },
  {
    pattern: /([（(])(\d{1,3})[）)][ \t\u00a0\u3000]*/g,
    number: match => Number(match[2]),
    style: match => match[1],
  },
  {
    pattern: /[\u2460-\u2473][ \t\u00a0\u3000]*/g,
    number: match => match[0].charCodeAt(0) - 0x2460 + 1,
    style: () => '',
  },
  // A number, a space and a short named term ending in a colon: "1 恶性肿瘤——轻度：".
  {
    pattern: /(\d{1,3})[ \t\u00a0\u3000]+/g,
    number: match => Number(match[1]),
    style: () => '',
    named: true,
  },
]

function atBoundary(text: string, index: number): boolean {
  let at = index - 1
  while (at >= 0 && SPACE.test(text[at])) at--
  return at < 0 || BOUNDARY.has(text[at])
}

function quotedPositions(text: string): boolean[] {
  const quoted: boolean[] = []
  let depth = 0
  for (const char of text) {
    if (CLOSING_QUOTES.has(char) && depth > 0) depth--
    // One flag per UTF-16 unit, so indexes match the string's.
    for (let unit = 0; unit < char.length; unit++) quoted.push(depth > 0)
    if (OPENING_QUOTES.has(char)) depth++
  }
  return quoted
}

// Every marker that may open an item, grouped by style in text order.
function markersByStyle(text: string): Map<string, Marker[]> {
  const quoted = quotedPositions(text)
  const styles = new Map<string, Marker[]>()
  FAMILIES.forEach((family, rank) => {
    const pattern = new RegExp(family.pattern.source, 'g')
    let match: RegExpExecArray | null
    while ((match = pattern.exec(text)) !== null) {
      if (quoted[match.index] || !atBoundary(text, match.index)) continue
      const end = match.index + match[0].length
      if (family.named && nameColon(text, quoted, end) <= end) continue
      const style = `${rank}${family.style(match)}`
      const marker = {
        start: match.index,
        end,
        number: family.number(match),
        text: match[0].trim(),
        style,
        rank,
      }
      styles.set(style, [...(styles.get(style) ?? []), marker])
    }
  })
  return styles
}

// Markers numbered 1, 2, 3 … in order. Once the list has begun, a marker of the same style with
// any other number ends it there: a list never skips a wrong number to find the next one.
function chainOf(markers: Marker[]): Marker[] {
  const chain: Marker[] = []
  for (const marker of markers) {
    if (marker.number === chain.length + 1) chain.push(marker)
    else if (chain.length > 0) break
  }
  return chain
}

// Where a short name starting at `from` ends: at its first colon outside quotes, or -1 when a
// sentence mark comes first or the name would run past MAX_LEAD characters.
function nameColon(text: string, quoted: boolean[], from: number): number {
  for (let index = from; index < text.length && index - from <= MAX_LEAD; index++) {
    if (LEAD_STOP.test(text[index])) return -1
    if ((text[index] === '：' || text[index] === ':') && !quoted[index]) return index
  }
  return -1
}

function splitLead(text: string): { lead: string; rest: string } {
  const colon = nameColon(text, quotedPositions(text), 0)
  if (colon <= 0 || LEAD_START_STOP.test(text.slice(0, colon))) return { lead: '', rest: text }
  return { lead: text.slice(0, colon + 1).trim(), rest: text.slice(colon + 1) }
}

function item(marker: string, text: string, used: Set<string>, depth: number): OutlineItem {
  const trimmed = text.trimStart()
  const whole = parse(trimmed, used, depth)
  // An item that opens straight with its sub-items has no name of its own; the first sub-item is
  // kept as the first child, never taken for the item's name.
  if (whole.items.length > 0 && whole.intro === '') return { marker, lead: '', body: '', children: whole.items }
  const { lead, rest } = splitLead(trimmed)
  const inner = lead ? parse(rest, used, depth) : whole
  return { marker, lead, body: inner.intro, children: inner.items }
}

function earlier(chain: Marker[], best: Marker[] | null): boolean {
  if (best === null) return true
  return chain[0].start < best[0].start || (chain[0].start === best[0].start && chain[0].rank < best[0].rank)
}

// `used` holds the styles of the enclosing levels, which a nested level never reuses.
function parse(text: string, used: Set<string>, depth: number): ValueOutline {
  let best: Marker[] | null = null
  if (depth < MAX_DEPTH) {
    for (const [style, markers] of markersByStyle(text)) {
      if (used.has(style)) continue
      const chain = chainOf(markers)
      if (chain.length >= 2 && earlier(chain, best)) best = chain
    }
  }
  if (best === null) return { intro: text.trim(), items: [] }
  const chain = best
  const nested = new Set([...used, chain[0].style])
  const items = chain.map((marker, index) => {
    const end = index + 1 < chain.length ? chain[index + 1].start : text.length
    return item(marker.text, text.slice(marker.end, end), nested, depth + 1)
  })
  return { intro: text.slice(0, chain[0].start).trim(), items }
}

export function valueOutline(value: string | string[]): ValueOutline {
  if (typeof value === 'string') return parse(value, new Set(), 0)
  if (value.length === 1) return parse(value[0], new Set(), 0)
  return { intro: '', items: value.map(text => item('', text, new Set(), 1)) }
}

function itemText(item: OutlineItem): string {
  return item.marker + item.lead + item.body + item.children.map(itemText).join('')
}

export function outlineText(outline: ValueOutline): string {
  return outline.intro + outline.items.map(itemText).join('')
}
