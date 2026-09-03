import {
  buildSchemaCitationContentPath,
  buildSchemaCitationPreviewRequest,
  buildSchemaWikiScopeBootstrapPath,
  type SchemaWikiCitationPreviewTransport,
  type SchemaWikiPreviewTransport,
  type SchemaWikiReadTransport,
} from './index.ts'
import {
  parseSchemaWikiScope,
  type SchemaWikiScopeV1,
} from '../../views/knowledge/schema-wiki/schemaWikiContract.ts'
import {
  assertEntityPageTarget830G1,
  parseEntityPageGraphRead830G1,
  type EntityPageGraphRead830G1,
  type EntityPageTarget830G1,
} from '../../views/knowledge/schema-wiki/entityPageGraph830G1Contract.ts'
import { buildScopedSchemaWikiPath } from '../../views/knowledge/schema-wiki/schemaWikiNavigation.ts'
import type { SchemaWikiCitationPreviewRequestV1 } from '../../components/schema-wiki/schemaCitationTarget.ts'

const ID_SEGMENT = /^[A-Za-z0-9._:@-]+$/

function exactID(value: string, errorCode: string): string {
  if (!ID_SEGMENT.test(value)) throw new Error(errorCode)
  return encodeURIComponent(value).replaceAll('%40', '@')
}

function exactReleaseID(releaseID: string | undefined): string | undefined {
  if (releaseID === undefined) return undefined
  if (releaseID === '' || releaseID !== releaseID.trim() || !ID_SEGMENT.test(releaseID)
    || ['current', 'latest'].includes(releaseID.toLowerCase())) {
    throw new Error('ENTITY_PAGE_GRAPH_RELEASE_ID_INVALID')
  }
  return releaseID
}

function exactPreparationID(preparationID: string | undefined): string | undefined {
  if (preparationID === undefined) return undefined
  if (preparationID === '' || preparationID !== preparationID.trim() || !ID_SEGMENT.test(preparationID)
    || ['current', 'latest'].includes(preparationID.toLowerCase())) {
    throw new Error('ENTITY_PAGE_GRAPH_PREPARATION_ID_INVALID')
  }
  return preparationID
}

function exactReadIdentity(releaseID?: string, preparationID?: string) {
  const release = exactReleaseID(releaseID)
  const preparation = exactPreparationID(preparationID)
  if (release !== undefined && preparation !== undefined) {
    throw new Error('ENTITY_PAGE_GRAPH_READ_MODE_INVALID')
  }
  return Object.freeze({ releaseID: release, preparationID: preparation })
}

function scopePayload(value: unknown): unknown {
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    const record = value as Record<string, unknown>
    if (record.success === true && Object.keys(record).length === 2 && 'data' in record) return record.data
  }
  return value
}

export function buildEntityPageGraphPath830G1(
  scope: SchemaWikiScopeV1,
  target: EntityPageTarget830G1,
  releaseID?: string,
  preparationID?: string,
): string {
  assertEntityPageTarget830G1(target)
  const entity = exactID(target.entityId, 'ENTITY_PAGE_GRAPH_TARGET_INVALID')
  let suffix = `/entities/${entity}`
  if (target.pageKind === 'overview') suffix += '/overview'
  if (target.pageKind === 'section') suffix += `/sections/${exactID(target.stableKey, 'ENTITY_PAGE_GRAPH_TARGET_INVALID')}`
  if (target.pageKind === 'field') suffix += `/fields/${exactID(target.stableKey, 'ENTITY_PAGE_GRAPH_TARGET_INVALID')}`
  if (target.pageKind === 'free_wiki') suffix += '/free-wiki'
  const path = buildScopedSchemaWikiPath(scope, suffix, { expectedScope: scope })
  const identity = exactReadIdentity(releaseID, preparationID)
  if (identity.releaseID !== undefined) return `${path}?release_id=${encodeURIComponent(identity.releaseID)}`
  if (identity.preparationID !== undefined) return `${path}?preparation_id=${encodeURIComponent(identity.preparationID)}`
  return path
}

export function buildEntityPageGraphPreparationScopeBootstrapPath830G1(
  wikiKBID: string,
  preparationID: string,
): string {
  return `/api/v1/knowledgebase/${exactID(wikiKBID, 'ENTITY_PAGE_GRAPH_SCOPE_INVALID')}`
    + `/wiki/preparations/${exactID(exactPreparationID(preparationID)!, 'ENTITY_PAGE_GRAPH_PREPARATION_ID_INVALID')}/schema-scope`
}

export async function readEntityPageGraph830G1(
  wikiKBID: string,
  target: EntityPageTarget830G1,
  releaseID: string | undefined,
  transport: SchemaWikiReadTransport,
  preparationID?: string,
): Promise<EntityPageGraphRead830G1> {
  return (await readEntityPageGraphSession830G1(
    wikiKBID,
    target,
    releaseID,
    transport,
    preparationID,
  )).read
}

export interface EntityPageGraphSession830G1 {
  readonly scope: SchemaWikiScopeV1
  readonly read: EntityPageGraphRead830G1
}

export async function readEntityPageGraphSession830G1(
  wikiKBID: string,
  target: EntityPageTarget830G1,
  releaseID: string | undefined,
  transport: SchemaWikiReadTransport,
  preparationID?: string,
): Promise<EntityPageGraphSession830G1> {
  assertEntityPageTarget830G1(target)
  exactID(wikiKBID, 'ENTITY_PAGE_GRAPH_SCOPE_INVALID')
  const identity = exactReadIdentity(releaseID, preparationID)
  const scope = parseSchemaWikiScope(scopePayload(
    await transport.get(identity.preparationID === undefined
      ? buildSchemaWikiScopeBootstrapPath(wikiKBID)
      : buildEntityPageGraphPreparationScopeBootstrapPath830G1(wikiKBID, identity.preparationID)),
  ))
  if (scope.wiki_kb_id !== wikiKBID) throw new Error('ENTITY_PAGE_GRAPH_SCOPE_INVALID')
  const response = await transport.get(buildEntityPageGraphPath830G1(
    scope, target, identity.releaseID, identity.preparationID,
  ))
  const read = parseEntityPageGraphRead830G1(response, target)
  if (read.member.space_id !== scope.space_id || read.member.wiki_kb_id !== scope.wiki_kb_id
    || (identity.releaseID !== undefined
      ? read.read_mode !== 'pinned' || read.release_id !== identity.releaseID
      : identity.preparationID !== undefined
        ? read.read_mode !== 'preparation' || read.preparation_id !== identity.preparationID
        : read.read_mode !== 'current')) {
    throw new Error('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
  }
  return Object.freeze({ scope, read })
}

export function createEntityPageGraphPreparationCitationTransport830G1(
  scope: SchemaWikiScopeV1,
  preparationID: string,
  entityID: string,
  fullCitationID: string,
  transport: SchemaWikiReadTransport & SchemaWikiPreviewTransport,
): SchemaWikiCitationPreviewTransport {
  const preparation = exactPreparationID(preparationID)!
  const entity = exactID(entityID, 'ENTITY_PAGE_GRAPH_TARGET_INVALID')
  if (!/^citation_[0-9a-f]{64}$/.test(fullCitationID)) {
    throw new Error('ENTITY_PAGE_GRAPH_CITATION_ID_INVALID')
  }
  return Object.freeze({
    getAuthority(request: SchemaWikiCitationPreviewRequestV1) {
      const exact = buildSchemaCitationPreviewRequest(request)
      const base = buildScopedSchemaWikiPath(
        scope,
        `/preparations/${exactID(preparation, 'ENTITY_PAGE_GRAPH_PREPARATION_ID_INVALID')}`
          + `/entities/${entity}/fields/${exactID(exact.field_id, 'ENTITY_PAGE_GRAPH_TARGET_INVALID')}`
          + `/citations/${exactID(fullCitationID, 'ENTITY_PAGE_GRAPH_CITATION_ID_INVALID')}/preview`,
        { expectedScope: scope },
      )
      return transport.get(base)
    },
    async getBytesByToken(opaqueToken: string): Promise<Uint8Array> {
      const bytes = await transport.getBytes(buildSchemaCitationContentPath(scope, opaqueToken))
      if (!(bytes instanceof Uint8Array) || bytes.byteLength === 0) {
        throw new Error('PDF_PREVIEW_UNAVAILABLE')
      }
      return bytes.slice()
    },
  })
}
