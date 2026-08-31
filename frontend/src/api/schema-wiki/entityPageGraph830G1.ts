import { buildSchemaWikiScopeBootstrapPath, type SchemaWikiReadTransport } from './index.ts'
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
): string {
  assertEntityPageTarget830G1(target)
  const entity = exactID(target.entityId, 'ENTITY_PAGE_GRAPH_TARGET_INVALID')
  let suffix = `/entities/${entity}`
  if (target.pageKind === 'overview') suffix += '/overview'
  if (target.pageKind === 'section') suffix += `/sections/${exactID(target.stableKey, 'ENTITY_PAGE_GRAPH_TARGET_INVALID')}`
  if (target.pageKind === 'field') suffix += `/fields/${exactID(target.stableKey, 'ENTITY_PAGE_GRAPH_TARGET_INVALID')}`
  if (target.pageKind === 'free_wiki') suffix += '/free-wiki'
  const path = buildScopedSchemaWikiPath(scope, suffix, { expectedScope: scope })
  const pinnedReleaseID = exactReleaseID(releaseID)
  return pinnedReleaseID === undefined ? path : `${path}?release_id=${encodeURIComponent(pinnedReleaseID)}`
}

export async function readEntityPageGraph830G1(
  wikiKBID: string,
  target: EntityPageTarget830G1,
  releaseID: string | undefined,
  transport: SchemaWikiReadTransport,
): Promise<EntityPageGraphRead830G1> {
  return (await readEntityPageGraphSession830G1(
    wikiKBID,
    target,
    releaseID,
    transport,
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
): Promise<EntityPageGraphSession830G1> {
  assertEntityPageTarget830G1(target)
  exactID(wikiKBID, 'ENTITY_PAGE_GRAPH_SCOPE_INVALID')
  const pinnedReleaseID = exactReleaseID(releaseID)
  const scope = parseSchemaWikiScope(scopePayload(
    await transport.get(buildSchemaWikiScopeBootstrapPath(wikiKBID)),
  ))
  if (scope.wiki_kb_id !== wikiKBID) throw new Error('ENTITY_PAGE_GRAPH_SCOPE_INVALID')
  const response = await transport.get(buildEntityPageGraphPath830G1(scope, target, pinnedReleaseID))
  const read = parseEntityPageGraphRead830G1(response, target)
  if (read.member.space_id !== scope.space_id || read.member.wiki_kb_id !== scope.wiki_kb_id
    || (pinnedReleaseID !== undefined
      ? read.read_mode !== 'pinned' || read.release_id !== pinnedReleaseID
      : read.read_mode !== 'current')) {
    throw new Error('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
  }
  return Object.freeze({ scope, read })
}
