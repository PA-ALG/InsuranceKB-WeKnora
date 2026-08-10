export type KnowledgeBaseTab = 'schema' | 'materials' | 'documents' | 'graph'

export interface SchemaWikiScopeIdentity {
  space_id: string
  raw_kb_id: string
  wiki_kb_id: string
  scope_sha256: string
}

export function resolveKnowledgeBaseDefaultTab(input: {
  wikiEnabled: boolean
  requestedTab?: string
}): KnowledgeBaseTab {
  const valid = new Set<KnowledgeBaseTab>(['schema', 'materials', 'documents', 'graph'])
  if (input.requestedTab && valid.has(input.requestedTab as KnowledgeBaseTab)) {
    return input.requestedTab as KnowledgeBaseTab
  }
  return input.wikiEnabled ? 'schema' : 'documents'
}

export function projectSchemaWikiNavigation(input: {
  domains: Array<{ domain_id: string; display_name: string; ordinal: number }>
  taxonomy: { nodes: Array<Record<string, unknown>> }
  schemaPack: {
    sections: Array<{ section_id: string; ordinal: number; field_ids: string[] }>
    fields: Array<{ field_id: string; ordinal: number }>
  }
}) {
  return Object.freeze({
    domains: Object.freeze([...input.domains].sort((left, right) => left.ordinal - right.ordinal)),
    taxonomy: Object.freeze([...input.taxonomy.nodes]),
    sections: Object.freeze([...input.schemaPack.sections].sort((left, right) => left.ordinal - right.ordinal)),
    fields: Object.freeze([...input.schemaPack.fields].sort((left, right) => left.ordinal - right.ordinal)),
  })
}

export function assertStableTaxonomyReparent(
  before: {
    entity_id: string
    version_id: string
    field_id: string
    citation_id: string
  },
  after: {
    entity_id: string
    version_id: string
    field_id: string
    citation_id: string
  },
): void {
  if (
    before.entity_id !== after.entity_id
    || before.version_id !== after.version_id
    || before.field_id !== after.field_id
    || before.citation_id !== after.citation_id
  ) {
    throw new Error('TAXONOMY_REPARENT_AUTHORITY_DRIFT')
  }
}

export function buildScopedSchemaWikiPath(
  scope: SchemaWikiScopeIdentity,
  suffix: string,
  options?: { expectedScope?: SchemaWikiScopeIdentity },
): string {
  const expected = options?.expectedScope
  if (expected && (
    scope.space_id !== expected.space_id
    || scope.raw_kb_id !== expected.raw_kb_id
    || scope.wiki_kb_id !== expected.wiki_kb_id
    || scope.scope_sha256 !== expected.scope_sha256
  )) {
    throw new Error('SCHEMA_WIKI_SCOPE_DRIFT')
  }
  if (
    !scope.space_id || !scope.raw_kb_id || !scope.wiki_kb_id
    || !/^\/[A-Za-z0-9_./:-]+$/.test(suffix)
    || suffix.includes('..')
  ) {
    throw new Error('SCHEMA_WIKI_SCOPE_INVALID')
  }
  return `/api/v1/knowledgebase/${encodeURIComponent(scope.wiki_kb_id)}`
    + `/wiki/release-scopes/${encodeURIComponent(scope.space_id)}`
    + `/raw/${encodeURIComponent(scope.raw_kb_id)}/schema${suffix}`
}
