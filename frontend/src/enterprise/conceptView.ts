import type { Release, ReleaseMember } from './enterpriseApi'
import { navigationTree } from './navigationView'
import { methodEntityIds } from './methodView'
import { entitySummaries } from './releaseView'
import { valueOutline } from './valueOutline'

export interface ConceptLink { key: string; title: string }
export interface ConceptRow {
  entityId: string; name: string; group: string; state: string; summary: string; evidenceCount: number; slug: string
}
export interface ConceptSummary {
  explanation: string
  statements: { text: string; refs: { slug: string; entityId: string; name: string }[] }[]
  stale: boolean
}
export interface ConceptView {
  // Only a published model-written definition; the profile description is written for extraction.
  key: string; title: string; definition: string; category: string; related: ConceptLink[]
  rows: ConceptRow[]; summary: ConceptSummary | null
}

type RecordValue = Record<string, unknown>
const text = (value: unknown): string => typeof value === 'string' ? value : ''
const records = (value: unknown): RecordValue[] => Array.isArray(value)
  ? value.filter((item): item is RecordValue => item !== null && typeof item === 'object' && !Array.isArray(item)) : []
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
const profiles = (release: Release) => release.members.filter(member => member.kind === 'presentation_profile')

function fieldLabels(release: Release) {
  const fields = new Map<string, { title: string; category: string }>()
  for (const profile of profiles(release)) {
    for (const section of records(profile.payload?.sections)) {
      for (const field of records(section.fields)) {
        const key = text(field.field_key)
        if (!key) continue
        const previous = fields.get(key)
        fields.set(key, {
          title: previous?.title || text(field.short_title),
          category: previous?.category || text(field.schema_category),
        })
      }
    }
  }
  return fields
}

export function conceptKeys(release: Release): string[] {
  const subjects = new Map<string, Set<string>>()
  // SK-3: method knowledge forms no concept; method predicates stay on method pages.
  const methods = methodEntityIds(release)
  for (const member of release.members) {
    const payload = member.payload
    if (member.kind !== 'claim' || !['present', 'absent_explicitly'].includes(text(payload?.state))) continue
    const key = text(payload?.predicate)
    const subject = text(payload?.subject_ref)
    if (!key || !subject || methods.has(subject)) continue
    if (!subjects.has(key)) subjects.set(key, new Set())
    subjects.get(key)!.add(subject)
  }
  const eligible = new Set([...subjects].filter(([, ids]) => ids.size >= 2).map(([key]) => key))
  const ordered = [...fieldLabels(release).keys()].filter(key => eligible.delete(key))
  return [...ordered, ...[...eligible].sort()]
}

function namesSummary(names: string[]): string {
  return names.slice(0, 3).join('；') + (names.length > 3 ? '…' : '')
}

export function liveSummary(state: string, value: string | string[] | null): string {
  if (state !== 'present' || value === null) return ''
  let summary: string
  if (Array.isArray(value)) {
    summary = namesSummary(value.map(item => item.match(/^([^：:。；;，,！!？?\r\n]+)[：:]/)?.[1]?.trim() || item))
  } else {
    const outline = valueOutline(value)
    summary = outline.items.length && outline.items.every(item => item.lead)
      ? namesSummary(outline.items.map(item => item.lead.slice(0, -1)))
      : (value.match(/^[\s\S]*?[。；;！？!?]/)?.[0] ?? value).trim()
  }
  const characters = Array.from(summary)
  return characters.length > 60 ? characters.slice(0, 60).join('') + '…' : summary
}

function summaryView(release: Release, key: string, names: Map<string, string>): ConceptSummary | null {
  const published = release.members.find(member => member.kind === 'concept' && text(member.payload?.concept_key) === key)
  if (!published) return null
  const payload = published.payload
  const claims = new Map(release.members.filter(member => member.kind === 'claim').map(member => [member.logical_slug, member]))
  const basedOn = payload?.based_on
  const digests = basedOn && typeof basedOn === 'object' && !Array.isArray(basedOn) ? Object.entries(basedOn) : []
  return {
    explanation: text(payload?.explanation),
    statements: records(payload?.statements).map(statement => ({
      text: text(statement.text),
      refs: strings(statement.refs).flatMap(slug => {
        const claim = claims.get(slug)
        const entityId = text(claim?.payload?.subject_ref)
        // A missing reference is never guessed from its slug or redirected to another release.
        return claim && entityId ? [{ slug, entityId, name: names.get(entityId) || entityId }] : []
      }),
    })),
    stale: digests.some(([slug, digest]) => claims.get(slug)?.member_digest !== digest),
  }
}

export function conceptView(release: Release, key: string): ConceptView | null {
  const keys = conceptKeys(release)
  if (!keys.includes(key)) return null
  const labels = fieldLabels(release)
  const field = labels.get(key)
  const published = release.members.find(member => member.kind === 'concept' && text(member.payload?.concept_key) === key)
  const readerDefinition = text(published?.payload?.definition).trim()
  const entities = entitySummaries(release)
  const grouped = navigationTree(release).flatMap(domain => domain.groups
    .filter(group => group.key !== '__other__').flatMap(group => group.entries))
  const groupedIds = new Set(grouped.map(entity => entity.entityId))
  // Keep all unmatched entries last, including "other" groups from earlier domains.
  const orderedEntities = [...grouped, ...entities.filter(entity => !groupedIds.has(entity.entityId))]
  const names = new Map(entities.map(entity => [entity.entityId, entity.name]))
  const claims = new Map<string, ReleaseMember[]>()
  for (const member of release.members) {
    if (member.kind !== 'claim' || text(member.payload?.predicate) !== key) continue
    const id = text(member.payload?.subject_ref)
    if (!claims.has(id)) claims.set(id, [])
    claims.get(id)!.push(member)
  }
  const rows = orderedEntities.flatMap(entity => {
    const profile = profiles(release).find(member => strings(member.payload?.classification_labels).some(label => entity.labels.includes(label)))
    return (claims.get(entity.entityId) ?? []).map(claim => {
      const payload = claim.payload
      const state = text(payload?.state)
      const value = payload?.value
      const display = Array.isArray(value) ? value.map(String) : value == null ? null : typeof value === 'object' ? JSON.stringify(value) : String(value)
      return { entityId: entity.entityId, name: entity.name, group: text(profile?.payload?.display_name), state,
        summary: liveSummary(state, display), evidenceCount: Array.isArray(payload?.evidence) ? payload.evidence.length : 0, slug: claim.logical_slug }
    })
  })
  return {
    key, title: field?.title || key, category: field?.category || '', rows, definition: readerDefinition,
    related: field?.category ? keys.filter(other => other !== key && labels.get(other)?.category === field.category)
      .map(other => ({ key: other, title: labels.get(other)?.title || other })) : [],
    summary: summaryView(release, key, names),
  }
}
