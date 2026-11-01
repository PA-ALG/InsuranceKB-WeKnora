import type { Release, ReleaseMember } from './enterpriseApi'
import { conceptKeys } from './conceptView'
import { navigationTree } from './navigationView'
import { methodEntityIds } from './methodView'

type RecordValue = Record<string, unknown>
const text = (value: unknown): string => typeof value === 'string' ? value : ''
const records = (value: unknown): RecordValue[] => Array.isArray(value)
  ? value.filter((item): item is RecordValue => !!item && typeof item === 'object' && !Array.isArray(item)) : []
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []

export interface OverviewValue { text: string; state: string; generated: boolean }
export interface OverviewCell { key: string; fullValue: string; values: OverviewValue[] }

export function overviewShortValue(value: string): string {
  const first = value.trim().replace(/^\d+(?:\.\s+|[)、]\s*)/, '').split(/[，。；;]/, 1)[0]!.trim()
  // Never start inside a signed/grouped number: a partial match would change the fact shown.
  const amounts = first.match(/(?<![\d.,+−-])[+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:个月|周岁|万元|日|天|月|年|岁|%|元|次|倍)/g) ?? []
  if (amounts.length === 1) return amounts[0]!
  const chars = Array.from(first)
  return chars.length > 24 ? chars.slice(0, 24).join('') + '…' : first
}

function originalValue(value: unknown): string {
  if (value == null) return ''
  if (Array.isArray(value)) return value.map(originalValue).join('；')
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function overviewCell(key: string, claims: ReleaseMember[]): OverviewCell {
  return {
    key, fullValue: claims.map(claim => originalValue(claim.payload?.value)).filter(Boolean).join('\n'),
    values: claims.length ? claims.map(claim => ({
      text: claim.payload?.state === 'present' ? overviewShortValue(originalValue(claim.payload.value)) : '',
      state: text(claim.payload?.state), generated: claim.payload?.origin === 'MODEL_GENERATED',
    })) : [{ text: '', state: 'unknown', generated: false }],
  }
}

// The directory is a projection of one release. Metadata and field names remain published data.
export function spaceHomeView(release: Release) {
  const navigation = release.members.find(member => member.kind === 'navigation')?.payload
  const titles = new Map<string, string>()
  for (const member of release.members.filter(member => member.kind === 'presentation_profile')) {
    for (const section of records(member.payload?.sections)) {
      for (const field of records(section.fields)) {
        const key = text(field.field_key)
        if (key && !titles.get(key)) titles.set(key, text(field.short_title))
      }
    }
  }
  const columns = [...new Set(strings(navigation?.overview_fields))].map(key => ({ key, title: titles.get(key) || key }))
  const claims = new Map<string, Map<string, ReleaseMember[]>>()
  const stated = new Map<string, Set<string>>()
  for (const member of release.members) {
    if (member.kind !== 'claim') continue
    const subject = text(member.payload?.subject_ref), key = text(member.payload?.predicate)
    if (!subject || !key) continue
    if (!claims.has(subject)) claims.set(subject, new Map())
    const fields = claims.get(subject)!
    if (!fields.has(key)) fields.set(key, [])
    fields.get(key)!.push(member)
    if (['present', 'absent_explicitly'].includes(text(member.payload?.state))) {
      if (!stated.has(key)) stated.set(key, new Set())
      stated.get(key)!.add(subject)
    }
  }
  // SK-3: the directory is the product overview; methods are reached from the navigation.
  const methods = methodEntityIds(release)
  const groups = navigationTree(release).flatMap(domain => domain.groups
    .map(group => ({ ...group, entries: group.entries.filter(entry => !methods.has(entry.entityId)) }))
    .filter(group => group.entries.length).map(group => ({
    key: group.key, id: JSON.stringify([domain.key, group.key]), title: group.title || domain.title,
    rows: group.entries.map(entry => ({ ...entry,
      cells: columns.map(column => overviewCell(column.key, claims.get(entry.entityId)?.get(column.key) ?? [])),
    })),
  })))
  // conceptKeys already follows profile field order; stable sorting preserves that order on ties.
  const concepts = conceptKeys(release).map(key => ({ key, title: titles.get(key) || key, count: stated.get(key)?.size ?? 0 }))
    .sort((a, b) => b.count - a.count)
  return { title: text(navigation?.display_name).trim(), columns, groups, concepts,
    productCount: groups.reduce((total, group) => total + group.rows.length, 0) }
}
