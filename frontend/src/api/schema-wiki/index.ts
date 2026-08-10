import { parseSchemaWikiScope, type SchemaWikiScopeV1 } from '../../views/knowledge/schema-wiki/schemaWikiContract.ts'
import { buildScopedSchemaWikiPath } from '../../views/knowledge/schema-wiki/schemaWikiNavigation.ts'

export interface SchemaWikiReadTransport {
  get(path: string): Promise<unknown>
}

export interface SchemaWikiClient {
  readonly scope: SchemaWikiScopeV1
  getDomains(): Promise<unknown>
  getCurrentTaxonomy(): Promise<unknown>
  getCurrentEntityVersion(entityId: string, versionId: string): Promise<unknown>
  getReleaseRoot(releaseId: string): Promise<unknown>
  getReleaseSection(releaseId: string, sectionId: string): Promise<unknown>
  getReleaseField(releaseId: string, fieldId: string): Promise<unknown>
  getPreparationRoot(preparationId: string): Promise<unknown>
  getPreparationSection(preparationId: string, sectionId: string): Promise<unknown>
  getPreparationField(preparationId: string, fieldId: string): Promise<unknown>
}

const ID_SEGMENT = /^[A-Za-z0-9._:-]+$/

function exactId(value: string): string {
  if (!ID_SEGMENT.test(value)) {
    throw new Error('SCHEMA_WIKI_SCOPE_INVALID')
  }
  return encodeURIComponent(value)
}

export function buildSchemaWikiScopeBootstrapPath(wikiKbId: string): string {
  return `/api/v1/knowledgebase/${exactId(wikiKbId)}/wiki/schema-scope`
}

export async function bootstrapSchemaWikiClient(
  wikiKbId: string,
  transport: SchemaWikiReadTransport,
): Promise<SchemaWikiClient> {
  const payload = await transport.get(buildSchemaWikiScopeBootstrapPath(wikiKbId))
  const scope = parseSchemaWikiScope(payload)
  if (scope.wiki_kb_id !== wikiKbId) {
    throw new Error('SCHEMA_WIKI_SCOPE_DRIFT')
  }

  const read = (suffix: string): Promise<unknown> => transport.get(
    buildScopedSchemaWikiPath(scope, suffix, { expectedScope: scope }),
  )
  const releasePath = (releaseId: string, suffix: string): string => (
    `/releases/${exactId(releaseId)}/${suffix}`
  )
  const preparationPath = (preparationId: string, suffix: string): string => (
    `/preparations/${exactId(preparationId)}/${suffix}`
  )

  return Object.freeze({
    scope,
    getDomains: () => read('/domains'),
    getCurrentTaxonomy: () => read('/taxonomy/current'),
    getCurrentEntityVersion: (entityId: string, versionId: string) => read(
      `/entities/${exactId(entityId)}/versions/${exactId(versionId)}/current`,
    ),
    getReleaseRoot: (releaseId: string) => read(releasePath(releaseId, 'root')),
    getReleaseSection: (releaseId: string, sectionId: string) => read(
      releasePath(releaseId, `sections/${exactId(sectionId)}`),
    ),
    getReleaseField: (releaseId: string, fieldId: string) => read(
      releasePath(releaseId, `fields/${exactId(fieldId)}`),
    ),
    getPreparationRoot: (preparationId: string) => read(preparationPath(preparationId, 'root')),
    getPreparationSection: (preparationId: string, sectionId: string) => read(
      preparationPath(preparationId, `sections/${exactId(sectionId)}`),
    ),
    getPreparationField: (preparationId: string, fieldId: string) => read(
      preparationPath(preparationId, `fields/${exactId(fieldId)}`),
    ),
  })
}
