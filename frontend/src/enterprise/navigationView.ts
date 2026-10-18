import type { Release } from './enterpriseApi'
import { entitySummaries, type EntitySummary } from './releaseView'

export interface NavigationGroup { key: string; title: string; entries: EntitySummary[] }
export interface NavigationDomain { key: string; title: string; groups: NavigationGroup[] }

type RecordValue = Record<string, unknown>
const text = (value: unknown): string => typeof value === 'string' ? value : ''
const records = (value: unknown): RecordValue[] => Array.isArray(value)
  ? value.filter((item): item is RecordValue => item !== null && typeof item === 'object' && !Array.isArray(item)) : []
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []

// Navigation order and membership are published data, including future domains.
export function navigationTree(release: Release): NavigationDomain[] {
  const entries = entitySummaries(release)
  const navigation = release.members.find(member => member.kind === 'navigation')
  if (!navigation) return [{ key: '', title: '', groups: [{ key: '', title: '', entries }] }]
  const domains = records(navigation.payload?.domains)
  const types = new Map<string, string>()
  for (const member of release.members) {
    if (member.kind === 'entity' && !types.has(text(member.payload?.entity_id))) {
      types.set(text(member.payload?.entity_id), text(member.payload?.entity_type))
    }
  }
  const remaining = new Set(entries)
  const tree = domains.map(domain => {
    const accepted = strings(domain.entity_types)
    const matching = entries.filter(entry => remaining.has(entry) && accepted.includes(types.get(entry.entityId) ?? ''))
    matching.forEach(entry => remaining.delete(entry))
    const ungrouped = new Set(matching)
    const groups = records(domain.groups).map(group => {
      const labels = strings(group.classification_labels)
      const grouped = matching.filter(entry => ungrouped.has(entry) && entry.labels.some(label => labels.includes(label)))
      grouped.forEach(entry => ungrouped.delete(entry))
      return { key: text(group.group_key), title: text(group.display_name), entries: grouped }
    }).filter(group => group.entries.length > 0)
    if (ungrouped.size) groups.push({ key: '__other__', title: '', entries: [...ungrouped] })
    return { key: text(domain.domain_key), title: text(domain.display_name), groups }
  }).filter(domain => domain.groups.length > 0)
  if (remaining.size) tree.push({ key: '__other__', title: '', groups: [{ key: '__other__', title: '', entries: [...remaining] }] })
  return tree
}
