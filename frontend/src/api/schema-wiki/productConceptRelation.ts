/** A relationship is a typed facet of the same immutable release member. */
export interface ProductConceptRelation {
  readonly contract: 'product-concept-relation.830.v1'
  readonly subject_type: 'PRODUCT'
  readonly object_type: 'CONCEPT'
  readonly predicate: 'benefit_reduced_by_advance_payment'
  readonly object_concept_id: string
  readonly object_definition_sha256: string
}
type Member = { kind: string; member_id: string; owner_id: string; payload: Record<string, unknown> }
type Hash = (contract: string, payload: unknown) => Promise<string>
const keys = ['contract', 'subject_type', 'object_type', 'predicate', 'object_concept_id', 'object_definition_sha256'].sort()
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value)
function invalid(): never { throw new Error('G3_RELATION_INVALID') }

export function productConceptRelation(member: Member): ProductConceptRelation | null {
  if (!Object.hasOwn(member.payload, 'business_relation')) return null
  const value = member.payload.business_relation
  if (member.kind !== 'free_wiki_item' || !record(value) || Object.keys(value).sort().join(',') !== keys.join(',')
    || value.contract !== 'product-concept-relation.830.v1' || value.subject_type !== 'PRODUCT' || value.object_type !== 'CONCEPT'
    || value.predicate !== 'benefit_reduced_by_advance_payment' || !/^concept_[0-9a-f]{64}$/.test(String(value.object_concept_id))
    || !/^[0-9a-f]{64}$/.test(String(value.object_definition_sha256))) return invalid()
  return value as unknown as ProductConceptRelation
}

export async function validateProductConceptRelations(members: readonly Member[], hash: Hash): Promise<void> {
  const targets = new Map(members.filter(m => m.kind === 'concept').map(m => [m.member_id, m]))
  for (const member of members) {
    const relation = productConceptRelation(member)
    if (!relation) continue
    const page = member.payload
    const provenance = page.content_provenance
    if (typeof page.entity_version !== 'string' || !page.entity_version.trim()
      || !Array.isArray(page.concept_ids) || page.concept_ids.length !== 1 || page.concept_ids[0] !== relation.object_concept_id
      || !Array.isArray(page.evidence) || !page.evidence.length || !record(provenance)
      || !Array.isArray(provenance.segments) || !provenance.segments.length
      || provenance.segments.some(s => !record(s) || s.origin !== 'SOURCE_SUPPORTED')) return invalid()
    const key = 'relation_' + await hash('product-concept-relation-identity.830.g2.v1', [
      page.space_id, page.entity_id, relation.predicate, relation.object_concept_id,
    ])
    if (key !== page.stable_key) return invalid()
    const target = targets.get(relation.object_concept_id)
    if (!target || target.payload.space_id !== page.space_id) return invalid()
    const definition = Object.fromEntries(Object.entries(target.payload).filter(([k]) => k !== 'aliases'))
    if (await hash('concept-definition.830.g2.v1', definition) !== relation.object_definition_sha256) return invalid()
  }
}
