import type { Release } from './enterpriseApi'
import { conceptKeys } from './conceptView'
import { navigationTree } from './navigationView'

export interface GraphNode {
  id: string
  kind: 'product' | 'concept'
  title: string
  group: string
  groupTitle: string
  degree: number
}
export interface GraphEdge { source: string; target: string }
export interface RelationGraph { nodes: GraphNode[]; edges: GraphEdge[] }

type RecordValue = Record<string, unknown>
const text = (value: unknown): string => typeof value === 'string' ? value : ''
const records = (value: unknown): RecordValue[] => Array.isArray(value)
  ? value.filter((item): item is RecordValue => !!item && typeof item === 'object' && !Array.isArray(item)) : []

export function relationGraph(release: Release): RelationGraph {
  const navigation = release.members.find(member => member.kind === 'navigation')
  // Older releases predate published navigation. Only explicit product entities qualify;
  // orphan claim subjects and service entities must never become products by accident.
  const legacyProducts = new Set(release.members.filter(member => member.kind === 'entity'
    && ['product', 'product_version', 'insurance_product'].includes(text(member.payload?.entity_type)))
    .map(member => text(member.payload?.entity_id)))
  const products: GraphNode[] = navigationTree(release)
    .filter(domain => !navigation || domain.key === 'product')
    .flatMap(domain => domain.groups.flatMap(group => group.entries
      .filter(entry => navigation || legacyProducts.has(entry.entityId))
      .map(entry => ({ id: `entity:${entry.entityId}`, kind: 'product' as const, title: entry.name,
        group: group.key, groupTitle: group.title, degree: 0 }))))
  const titles = new Map<string, string>()
  for (const member of release.members.filter(member => member.kind === 'presentation_profile')) {
    for (const section of records(member.payload?.sections)) {
      for (const field of records(section.fields)) {
        const key = text(field.field_key)
        if (key && !titles.get(key)) titles.set(key, text(field.short_title))
      }
    }
  }
  const publishedTitles = new Map<string, string>()
  for (const member of release.members.filter(member => member.kind === 'concept')) {
    const key = text(member.payload?.concept_key), title = text(member.payload?.title).trim()
    if (key && title && !publishedTitles.has(key)) publishedTitles.set(key, title)
  }
  const keys = conceptKeys(release)
  const concepts: GraphNode[] = keys.map(key => ({ id: `concept:${key}`, kind: 'concept',
    title: publishedTitles.get(key) || titles.get(key) || key, group: '', groupTitle: '', degree: 0 }))
  const stated = new Map<string, Set<string>>()
  for (const member of release.members) {
    if (member.kind !== 'claim' || !['present', 'absent_explicitly'].includes(text(member.payload?.state))) continue
    const subject = text(member.payload?.subject_ref)
    if (!stated.has(subject)) stated.set(subject, new Set())
    stated.get(subject)!.add(text(member.payload?.predicate))
  }
  // Iterate published node order, independent of claim/applicability order; one edge per pair.
  const edges: GraphEdge[] = []
  for (const product of products) {
    const fields = stated.get(product.id.slice('entity:'.length))
    concepts.forEach((concept, index) => {
      if (!fields?.has(keys[index]!)) return
      edges.push({ source: product.id, target: concept.id })
      product.degree++
      concept.degree++
    })
  }
  return { nodes: [...products, ...concepts], edges }
}
