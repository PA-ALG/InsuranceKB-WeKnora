import type { Release, ReleaseMember } from './enterpriseApi'
import { navigationTree } from './navigationView'
import { entitySummaries, entityTypes, profileMemberFor } from './releaseView'

export interface FieldHit {
  entityId: string; name: string; slug: string; fieldKey: string; fieldTitle: string
  parts: { text: string; mark: boolean }[]
}
type RecordValue = Record<string, unknown>
const text = (value: unknown): string => typeof value === 'string' ? value : ''
const records = (value: unknown): RecordValue[] => Array.isArray(value)
  ? value.filter((item): item is RecordValue => !!item && typeof item === 'object' && !Array.isArray(item)) : []
const fold = (value: string) => value.normalize('NFKC').toLowerCase().replace(/\s+/gu, ' ').trim()
const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' })

function valueText(value: unknown): string {
  if (value == null) return ''
  if (Array.isArray(value)) return value.map(valueText).filter(item => item.trim()).join('；')
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

// Retain original graphemes for display; normalized expansions (e.g. ligatures) map back
// to their whole source character. Lowercase the entire string for contextual case rules.
function indexedText(value: string) {
  const chars = [...segmenter.segment(value.replace(/\s+/gu, ' ').trim())].map(item => item.segment)
  const normalized = chars.map(char => char.normalize('NFKC'))
  const owners = normalized.flatMap((part, index) => Array.from(part)
    .flatMap(char => Array(char.toLowerCase().length).fill(index) as number[]))
  const lower = normalized.join('').toLowerCase(), offsets: number[] = []
  let folded = ''
  for (let index = 0; index < lower.length; index++) {
    const char = /\s/u.test(lower[index]!) ? ' ' : lower[index]!
    if (char === ' ' && (!folded || folded.endsWith(' '))) continue
    folded += char; offsets.push(owners[index]!)
  }
  if (folded.endsWith(' ')) { folded = folded.slice(0, -1); offsets.pop() }
  return { chars, folded, offsets }
}

function snippet(value: string, terms: string[]): FieldHit['parts'] {
  const { chars, folded, offsets } = indexedText(value)
  const matches: [number, number][] = []
  let anchor: [number, number] | undefined
  for (const term of terms) {
    for (let at = folded.indexOf(term); at !== -1; at = folded.indexOf(term, at + 1)) {
      const range: [number, number] = [offsets[at]!, offsets[at + term.length - 1]! + 1]
      anchor ??= range
      matches.push(range)
    }
  }
  const start = Math.max(0, (anchor?.[0] ?? 0) - 20)
  const end = Math.min(chars.length, (anchor?.[1] ?? 0) + 40)
  const marked = new Set<number>()
  for (const [left, right] of matches) {
    for (let index = Math.max(start, left); index < Math.min(end, right); index++) marked.add(index)
  }
  const parts: FieldHit['parts'] = []
  function append(value: string, mark: boolean) {
    const last = parts.at(-1)
    if (last?.mark === mark) last.text += value
    else parts.push({ text: value, mark })
  }
  if (start) append('…', false)
  for (let index = start; index < end; index++) append(chars[index]!, marked.has(index))
  if (end < chars.length) append('…', false)
  return parts
}

export function searchFields(release: Release, query: string, limit = 50): { hits: FieldHit[]; total: number } {
  const terms = [...new Set(fold(query).split(' ').filter(Boolean))]
  const hits: FieldHit[] = []
  if (!terms.length) return { hits, total: 0 }
  const maximum = Math.max(0, Math.floor(limit)) || 0
  const grouped = navigationTree(release).flatMap(domain => domain.groups
    .filter(group => group.key !== '__other__').flatMap(group => group.entries))
  const groupedIds = new Set(grouped.map(entity => entity.entityId))
  const ordered = [...grouped, ...entitySummaries(release).filter(entity => !groupedIds.has(entity.entityId))]
  const types = entityTypes(release)
  const claims = new Map<string, ReleaseMember[]>()
  for (const member of release.members) {
    if (member.kind !== 'claim' || member.payload?.state !== 'present') continue
    const subject = text(member.payload.subject_ref)
    if (!claims.has(subject)) claims.set(subject, [])
    claims.get(subject)!.push(member)
  }
  let total = 0
  for (const entity of ordered) {
    const profile = profileMemberFor(release, types.get(entity.entityId) ?? '', entity.labels)
    const fields = records(profile?.sections).flatMap(section => records(section.fields))
    const titles = new Map<string, string>(), order = new Map<string, number>()
    for (const field of fields) {
      const key = text(field.field_key)
      if (!key || order.has(key)) continue
      order.set(key, order.size); titles.set(key, text(field.short_title) || key)
    }
    const rank = (member: ReleaseMember) => order.get(text(member.payload.predicate)) ?? order.size
    // Stable sort preserves every Claim and member order among unknown fields or equal keys.
    for (const member of (claims.get(entity.entityId) ?? []).slice().sort((a, b) => rank(a) - rank(b))) {
      const fieldKey = text(member.payload.predicate), value = valueText(member.payload.value)
      if (!fieldKey || !value.trim()) continue
      const fieldTitle = titles.get(fieldKey) || fieldKey, title = fold(fieldTitle), content = fold(value)
      if (!terms.every(term => title.includes(term) || content.includes(term))) continue
      total++
      if (hits.length < maximum) hits.push({ entityId: entity.entityId, name: entity.name,
        slug: member.logical_slug, fieldKey, fieldTitle, parts: snippet(value, terms) })
    }
  }
  return { hits, total }
}
