import { parseSchemaWikiScope, type SchemaWikiScopeV1 } from '../../views/knowledge/schema-wiki/schemaWikiContract.ts'
import { buildScopedSchemaWikiPath } from '../../views/knowledge/schema-wiki/schemaWikiNavigation.ts'
import type { SchemaWikiCitationPreviewRequestV1 } from '../../components/schema-wiki/schemaCitationTarget.ts'

export interface SchemaWikiReadTransport {
  get(path: string): Promise<unknown>
}

export interface SchemaWikiPreviewTransport {
  getBytes(path: string): Promise<Uint8Array>
}

export interface SchemaWikiCitationPreviewTransport {
  getAuthority(request: SchemaWikiCitationPreviewRequestV1): Promise<unknown>
  getBytesByToken(opaqueToken: string): Promise<Uint8Array>
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
  getGoldenQualitySummary(preparationId: string, evaluationId: string): Promise<unknown>
  getGoldenQualityDossier(preparationId: string, evaluationId: string): Promise<unknown>
  getGoldenSuccessorStatus(): Promise<unknown>
  getGoldenEvidencePreview(
    preparationId: string,
    evaluationId: string,
    fieldId: string,
    evidenceId: string,
  ): Promise<unknown>
}

const ID_SEGMENT = /^[A-Za-z0-9._:-]+$/
const ENTITY_VERSION_ID_SEGMENT = /^[A-Za-z0-9._:@-]+$/

export function buildSchemaCitationPreviewRequest(
  input: SchemaWikiCitationPreviewRequestV1,
): SchemaWikiCitationPreviewRequestV1 {
  if (
    !input || Object.keys(input).sort().join(',') !== 'activation_epoch,citation_id,field_id,release_id'
    || !ID_SEGMENT.test(input.release_id)
    || !Number.isSafeInteger(input.activation_epoch) || input.activation_epoch <= 0
    || !ID_SEGMENT.test(input.field_id)
    || !ID_SEGMENT.test(input.citation_id)
  ) {
    throw new Error('CITATION_PREVIEW_REQUEST_INVALID')
  }
  return Object.freeze({ ...input })
}

function exactId(value: string): string {
  if (!ID_SEGMENT.test(value)) {
    throw new Error('SCHEMA_WIKI_SCOPE_INVALID')
  }
  return encodeURIComponent(value)
}

function exactEntityVersionId(value: string): string {
  if (!ENTITY_VERSION_ID_SEGMENT.test(value)) {
    throw new Error('SCHEMA_WIKI_SCOPE_INVALID')
  }
  return encodeURIComponent(value).replaceAll('%40', '@')
}

export function buildSchemaWikiScopeBootstrapPath(wikiKbId: string): string {
  return `/api/v1/knowledgebase/${exactId(wikiKbId)}/wiki/schema-scope`
}

export function buildSchemaCitationPreviewPath(
  scope: SchemaWikiScopeV1,
  releaseId: string,
  fieldId: string,
  citationId: string,
): string {
  return buildScopedSchemaWikiPath(
    scope,
    `/releases/${exactId(releaseId)}/fields/${exactId(fieldId)}`
      + `/citations/${exactId(citationId)}/preview`,
    { expectedScope: scope },
  )
}

export function buildSchemaCitationContentPath(
  scope: SchemaWikiScopeV1,
  opaqueToken: string,
): string {
  return buildScopedSchemaWikiPath(
    scope,
    `/citation-content/${exactId(opaqueToken)}`,
    { expectedScope: scope },
  )
}

export function createSchemaWikiCitationPreviewTransport(
  scope: SchemaWikiScopeV1,
  transport: SchemaWikiReadTransport & SchemaWikiPreviewTransport,
): SchemaWikiCitationPreviewTransport {
  return Object.freeze({
    getAuthority(request: SchemaWikiCitationPreviewRequestV1): Promise<unknown> {
      const exact = buildSchemaCitationPreviewRequest(request)
      return transport.get(buildSchemaCitationPreviewPath(
        scope,
        exact.release_id,
        exact.field_id,
        exact.citation_id,
      ))
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

export async function readPinnedSchemaCitationPreview(
  scope: SchemaWikiScopeV1,
  releaseId: string,
  fieldId: string,
  citationId: string,
  transport: SchemaWikiPreviewTransport,
): Promise<Uint8Array> {
  void scope
  void releaseId
  void fieldId
  void citationId
  void transport
  throw new Error('CITATION_PREVIEW_AUTHORITY_REQUIRED')
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
  const goldenQualityPath = (
    preparationId: string,
    evaluationId: string,
    suffix: string,
  ): string => preparationPath(
    preparationId,
    `golden-quality/evaluations/${exactId(evaluationId)}/${suffix}`,
  )

  return Object.freeze({
    scope,
    getDomains: () => read('/domains'),
    getCurrentTaxonomy: () => read('/taxonomy/current'),
    getCurrentEntityVersion: (entityId: string, versionId: string) => read(
      `/entities/${exactId(entityId)}/versions/${exactEntityVersionId(versionId)}/current`,
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
    getGoldenQualitySummary: (preparationId: string, evaluationId: string) => read(
      goldenQualityPath(preparationId, evaluationId, 'summary'),
    ),
    getGoldenQualityDossier: (preparationId: string, evaluationId: string) => read(
      goldenQualityPath(preparationId, evaluationId, 'dossier'),
    ),
    getGoldenSuccessorStatus: () => read('/golden-quality/successor-status'),
    getGoldenEvidencePreview: (
      preparationId: string,
      evaluationId: string,
      fieldId: string,
      evidenceId: string,
    ) => read(goldenQualityPath(
      preparationId,
      evaluationId,
      `fields/${exactId(fieldId)}/evidence/${exactId(evidenceId)}/preview`,
    )),
  })
}
