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
}

interface Family {
  pattern: RegExp
  number: (match: RegExpExecArray) => number
}

const MAX_DEPTH = 3
const MAX_LEAD = 32
// A marker only opens an item at the start of the text or right after one of these characters,
// so "第（1）项", "“8.轻度疾病释义”" and "编码3、6、9" stay inside the sentence.
const BOUNDARY = new Set(['。', '；', ';', '！', '!', '？', '?', '：', ':', '\n', '\r'])
const SPACE = /[ \t\u00a0\u3000]/
const LEAD_STOP = /[。；;，,！!？?\n\r]/

// Earlier families win a tie at the same position.
const FAMILIES: Family[] = [
  { pattern: /(\d{1,3})[.．、](?!\d)[ \t\u00a0\u3000]*/g, number: match => Number(match[1]) },
  { pattern: /[（(](\d{1,3})[）)][ \t\u00a0\u3000]*/g, number: match => Number(match[1]) },
  { pattern: /[①-⑳][ \t\u00a0\u3000]*/g, number: match => match[0].charCodeAt(0) - 0x2460 + 1 },
  // A number, a space and a short named term ending in a colon: "1 恶性肿瘤——轻度：".
  {
    pattern: /(\d{1,3})[ \t\u00a0\u3000]+(?=[^\n\r：:。；;，,！!？?]{1,32}[：:])/g,
    number: match => Number(match[1]),
  },
]

function atBoundary(text: string, index: number): boolean {
  let at = index - 1
  while (at >= 0 && SPACE.test(text[at])) at--
  return at < 0 || BOUNDARY.has(text[at])
}

// Markers numbered 1, 2, 3 … in order; the first missing number ends the list.
function chainOf(text: string, family: Family): Marker[] {
  const chain: Marker[] = []
  const pattern = new RegExp(family.pattern.source, 'g')
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    if (family.number(match) !== chain.length + 1 || !atBoundary(text, match.index)) continue
    chain.push({ start: match.index, end: match.index + match[0].length, number: chain.length + 1, text: match[0].trim() })
  }
  return chain
}

function splitLead(text: string): { lead: string; rest: string } {
  const trimmed = text.trimStart()
  const colon = trimmed.search(/[：:]/)
  if (colon <= 0 || colon > MAX_LEAD || LEAD_STOP.test(trimmed.slice(0, colon))) return { lead: '', rest: trimmed }
  return { lead: trimmed.slice(0, colon + 1).trim(), rest: trimmed.slice(colon + 1) }
}

function item(marker: string, text: string, families: Family[], depth: number): OutlineItem {
  const { lead, rest } = splitLead(text)
  const inner = parse(rest, families, depth)
  return { marker, lead, body: inner.intro, children: inner.items }
}

function parse(text: string, families: Family[], depth: number): ValueOutline {
  let best: { family: Family; chain: Marker[] } | null = null
  if (depth < MAX_DEPTH) {
    for (const family of families) {
      const chain = chainOf(text, family)
      if (chain.length >= 2 && (best === null || chain[0].start < best.chain[0].start)) best = { family, chain }
    }
  }
  if (best === null) return { intro: text.trim(), items: [] }
  const { family, chain } = best
  const rest = families.filter(other => other !== family)
  const items = chain.map((marker, index) => {
    const end = index + 1 < chain.length ? chain[index + 1].start : text.length
    return item(marker.text, text.slice(marker.end, end), rest, depth + 1)
  })
  return { intro: text.slice(0, chain[0].start).trim(), items }
}

export function valueOutline(value: string | string[]): ValueOutline {
  if (typeof value === 'string') return parse(value, FAMILIES, 0)
  if (value.length === 1) return parse(value[0], FAMILIES, 0)
  return { intro: '', items: value.map(text => item('', text, FAMILIES, 1)) }
}

function itemText(item: OutlineItem): string {
  return item.marker + item.lead + item.body + item.children.map(itemText).join('')
}

export function outlineText(outline: ValueOutline): string {
  return outline.intro + outline.items.map(itemText).join('')
}
