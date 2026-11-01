import type { Release, ReleaseMember } from './enterpriseApi'
import { navigationTree } from './navigationView'
import { entityView, profileMemberFor, type EntitySummary } from './releaseView'

// SK-3 (Spec docs/design/slices/SK-3-销售方法阅读与问答.md §5): method knowledge is recognised from
// published data only — an entity whose type a presentation profile with knowledge_class "method"
// serves. Its list values cite each item with the evidence at its position (SK-2 §4.3).

type Payload = Record<string, unknown>
const text = (value: unknown): string => typeof value === 'string' ? value : ''
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
const records = (value: unknown): Payload[] => Array.isArray(value)
  ? value.filter((item): item is Payload => !!item && typeof item === 'object' && !Array.isArray(item)) : []

const METHOD = 'method'
const FAMILY = 'family:' // SK-0 §2.2: a label naming a product family by its product_family.key

export interface MethodLabel { label: string; title: string; family?: { title: string; products: EntitySummary[] } }
export interface MethodField {
  slug: string; title: string; state: string; text: string | null; items: string[] | null; evidenceCount: number
}
export interface MethodMaterial { sourceRef: string; member: string; evidence: number }
export interface MethodView {
  entityId: string; name: string; notice: string; noticeText: string; labels: MethodLabel[]
  fields: MethodField[]; materials: MethodMaterial[]; updatedAt: string
}

function entities(release: Release): Payload[] {
  return release.members.filter(member => member.kind === 'entity').map(member => member.payload ?? {})
}

/** The entities method profiles serve. */
export function methodEntityIds(release: Release): Set<string> {
  const out = new Set<string>()
  for (const entity of entities(release)) {
    const profile = profileMemberFor(release, text(entity.entity_type), strings(entity.classification_labels))
    if (profile?.knowledge_class === METHOD && strings(profile.entity_types).includes(text(entity.entity_type))) {
      out.add(text(entity.entity_id))
    }
  }
  return out
}

function ordered(release: Release): EntitySummary[] {
  return navigationTree(release).flatMap(domain => domain.groups.flatMap(group => group.entries))
}

function payloadOf(release: Release, entityId: string): Payload | undefined {
  return entities(release).find(entity => text(entity.entity_id) === entityId)
}

/** A product's related methods (§5.4): family-labelled ones first, then label matches, in navigation order. */
export function relatedMethods(release: Release, productId: string): EntitySummary[] {
  const methods = methodEntityIds(release)
  const product = payloadOf(release, productId)
  if (!product || methods.has(productId)) return []
  const family = text((product.product_family as Payload | undefined)?.key)
  const labels = strings(product.classification_labels)
  const entries = ordered(release).filter(entry => methods.has(entry.entityId))
  const byFamily = family ? entries.filter(entry => entry.labels.includes(FAMILY + family)) : []
  const byLabel = entries.filter(entry => !byFamily.includes(entry) && entry.labels.some(label => labels.includes(label)))
  return [...byFamily, ...byLabel]
}

function labelTitle(release: Release, label: string): string {
  const navigation = release.members.find(member => member.kind === 'navigation')
  for (const domain of records(navigation?.payload?.domains)) {
    for (const group of records(domain.groups)) {
      if (strings(group.classification_labels).includes(label) && text(group.display_name)) return text(group.display_name)
    }
  }
  return label
}

function methodLabel(release: Release, label: string): MethodLabel {
  if (!label.startsWith(FAMILY)) return { label, title: labelTitle(release, label) }
  const key = label.slice(FAMILY.length)
  const members = entities(release).filter(entity => text((entity.product_family as Payload | undefined)?.key) === key)
  const title = text((members[0]?.product_family as Payload | undefined)?.display_name) || key
  const ids = new Set(members.map(entity => text(entity.entity_id)))
  const products = ordered(release).filter(entry => ids.has(entry.entityId))
  return { label, title, family: { title, products } }
}

function claimsOf(release: Release, entityId: string): Map<string, ReleaseMember> {
  return new Map(release.members.filter(member => member.kind === 'claim' && member.payload?.subject_ref === entityId)
    .map(member => [member.logical_slug, member]))
}

function alignedItems(value: unknown, evidence: number): string[] | null {
  if (!Array.isArray(value) || !value.length || value.length !== evidence) return null
  return value.every(item => typeof item === 'string' && item.trim()) ? value as string[] : null
}

/** The method page of an entry, or null when it is no method of this release. */
export function methodView(release: Release, entityId: string): MethodView | null {
  if (!methodEntityIds(release).has(entityId)) return null
  const view = entityView(release, entityId)
  const entity = payloadOf(release, entityId)
  if (!view || !entity) return null
  const claims = claimsOf(release, entityId)
  const fields = [...view.sections.flatMap(section => section.fields), ...view.other, ...view.generated].map(field => {
    const payload = claims.get(field.slug)?.payload ?? {}
    const items = field.state === 'present' ? alignedItems(payload.value, field.evidenceCount) : null
    const value = field.value
    return {
      slug: field.slug, title: field.title, state: field.state, items, evidenceCount: field.evidenceCount,
      text: items || value === null ? null : Array.isArray(value) ? value.join('；') : value,
    }
  })
  const materials: MethodMaterial[] = []
  let updatedAt = ''
  for (const field of fields) {
    const payload = claims.get(field.slug)?.payload ?? {}
    records(payload.evidence).forEach((evidence, index) => {
      const ref = text(evidence.source_ref)
      if (ref && !materials.some(material => material.sourceRef === ref)) materials.push({ sourceRef: ref, member: field.slug, evidence: index })
    })
    const changed = text((payload.maintenance as Payload | undefined)?.changed_at)
    if (changed && (!updatedAt || Date.parse(changed) > Date.parse(updatedAt))) updatedAt = changed
  }
  const notice = text((entity.identifiers as Payload | undefined)?.notice)
  const profile = profileMemberFor(release, text(entity.entity_type), strings(entity.classification_labels))
  const noticeText = notice ? text((profile?.notices as Payload | undefined)?.[notice]) : ''
  return {
    entityId, name: view.name, notice: noticeText ? notice : '', noticeText,
    labels: strings(entity.classification_labels).map(label => methodLabel(release, label)),
    fields, materials, updatedAt,
  }
}
