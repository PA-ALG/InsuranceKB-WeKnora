import { buildSchemaWikiScopeBootstrapPath, type SchemaWikiReadTransport } from './index.ts'
import { parseSchemaWikiScope, type SchemaWikiScopeV1 } from '../../views/knowledge/schema-wiki/schemaWikiContract.ts'
import { buildScopedSchemaWikiPath } from '../../views/knowledge/schema-wiki/schemaWikiNavigation.ts'

export const CATALOG_ID_830_G3 = 'schema_catalog_insurance_product'
export const CATALOG_VERSION_830_G3 = '2026-08-12-v5'
export const CATALOG_CONTENT_SHA256_830_G3 = 'b4b8cd9c797442c3581c8721834abb3f6ec716057509dad4ac254f79fc0a97bd'
export const CATALOG_WIRE_SHA256_830_G3 = '0d5ed6a5789362f1c72ebad5bbc47a64e1d71bc122890da96d976ec01256a3f9'

const CATALOG_CONTRACT = 'schema-pack-catalog.830.g3.v1'
const PACK_CONTRACT = 'schema-pack-definition.830.g3.v1'
const FIELD_CONTRACT = 'schema-field-definition.830.g3.v1'
const PROFILE_CONTRACT = 'presentation-profile.v1'
const HASH = /^[0-9a-f]{64}$/
const FIELD_KEY = /^[A-Za-z][A-Za-z0-9_]*$/
const CONTROL = /[\u0000-\u001f\u007f]/
const encoder = new TextEncoder()
type RecordValue = Record<string, unknown>

export interface SchemaPackField830G3 {
  readonly field_key: string
  readonly short_title: string
  readonly schema_category: string
  readonly value_spec: string | null
  readonly description: string | null
  readonly source_guidance: string | null
  readonly formation_method: string | null
  readonly knowledge_role: string | null
  readonly common_field_marker: string | null
  readonly other_applicable_products: string | null
  readonly usage_frequency: number
  readonly source_row: number
  readonly semantic_sha256: string
}

export interface SchemaPackDefinition830G3 {
  readonly contract: typeof PACK_CONTRACT
  readonly schema_pack_id: string
  readonly schema_version: string
  readonly display_name: string
  readonly entity_type: 'insurance_product'
  readonly applicable_classifications: readonly string[]
  readonly workbook_sha256: string
  readonly workbook_sheet: string
  readonly fields: readonly SchemaPackField830G3[]
  readonly presentation_profile_ref: { readonly profile_id: string, readonly profile_version: string }
  readonly schema_pack_sha256: string
}

export interface PresentationProfile830G3 {
  readonly contract: typeof PROFILE_CONTRACT
  readonly profile_id: string
  readonly profile_version: string
  readonly schema_pack_id: string
  readonly schema_version: string
  readonly schema_pack_sha256: string
  readonly sections: readonly {
    readonly section_key: string
    readonly display_name: string
    readonly fields: readonly { readonly field_key: string, readonly short_title: string }[]
  }[]
  readonly profile_sha256: string
}

export interface SchemaPackCatalog830G3 {
  readonly contract: typeof CATALOG_CONTRACT
  readonly catalog_id: typeof CATALOG_ID_830_G3
  readonly catalog_version: typeof CATALOG_VERSION_830_G3
  readonly workbook_sha256: string
  readonly mapping_config_sha256: string
  readonly entries: readonly {
    readonly pack: SchemaPackDefinition830G3
    readonly profile: PresentationProfile830G3
    readonly profile_confirmation_status: 'PENDING_PRODUCT_OWNER_CONFIRMATION'
    readonly quality_status: 'REGISTERED_NOT_QUALITY_ADMITTED'
  }[]
  readonly field_name_union_count: number
  readonly field_name_intersection_count: number
  readonly catalog_sha256: typeof CATALOG_CONTENT_SHA256_830_G3
}

export interface SchemaPackCatalogSession830G3 {
  readonly scope: SchemaWikiScopeV1
  readonly catalog: SchemaPackCatalog830G3
}

function invalid(): never {
  throw new Error('SCHEMA_PACK_CATALOG_830_G3_INVALID')
}

function isRecord(value: unknown): value is RecordValue {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function exactKeys(value: RecordValue, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
}

function text(value: unknown, allowEmpty = false): value is string {
  return typeof value === 'string'
    && (allowEmpty || value.length > 0)
    && value.normalize('NFC') === value
    && !CONTROL.test(value)
}

function id(value: unknown): value is string {
  return text(value) && value.length <= 512 && value.trim() === value
}

function hash(value: unknown): value is string {
  return typeof value === 'string' && HASH.test(value)
}

function nullableText(value: unknown): value is string | null {
  return value === null || text(value, true)
}

function canonicalJSON(value: unknown): string {
  if (value === null || typeof value === 'boolean') return JSON.stringify(value)
  if (typeof value === 'string') {
    if (!text(value, true)) invalid()
    return JSON.stringify(value)
  }
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) invalid()
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJSON).join(',')}]`
  if (!isRecord(value)) invalid()
  return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJSON(value[key])}`).join(',')}}`
}

async function sha256(textValue: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', encoder.encode(textValue))
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}

async function schemaWikiHash(contract: string, payload: unknown): Promise<string> {
  return sha256(`schema-wiki-canonical.v1\u0000${contract}\u0000${canonicalJSON(payload)}`)
}

function without(value: RecordValue, key: string): RecordValue {
  return Object.fromEntries(Object.entries(value).filter(([name]) => name !== key))
}

function assertField(value: unknown): asserts value is SchemaPackField830G3 & RecordValue {
  const keys = [
    'field_key', 'short_title', 'schema_category', 'value_spec', 'description',
    'source_guidance', 'formation_method', 'knowledge_role', 'common_field_marker',
    'other_applicable_products', 'usage_frequency', 'source_row', 'semantic_sha256',
  ]
  if (!isRecord(value) || !exactKeys(value, keys) || typeof value.field_key !== 'string'
    || !FIELD_KEY.test(value.field_key) || !text(value.short_title, true)
    || !text(value.schema_category, true) || !nullableText(value.value_spec)
    || !nullableText(value.description) || !nullableText(value.source_guidance)
    || !nullableText(value.formation_method) || !nullableText(value.knowledge_role)
    || !nullableText(value.common_field_marker) || !nullableText(value.other_applicable_products)
    || !Number.isSafeInteger(value.usage_frequency) || !Number.isSafeInteger(value.source_row)
    || (value.source_row as number) <= 5 || !hash(value.semantic_sha256)) invalid()
}

function assertProfile(value: unknown): asserts value is PresentationProfile830G3 & RecordValue {
  const keys = ['contract', 'profile_id', 'profile_version', 'schema_pack_id', 'schema_version',
    'schema_pack_sha256', 'sections', 'profile_sha256']
  if (!isRecord(value) || !exactKeys(value, keys) || value.contract !== PROFILE_CONTRACT
    || !id(value.profile_id) || !id(value.profile_version) || !id(value.schema_pack_id)
    || !id(value.schema_version) || !hash(value.schema_pack_sha256)
    || !hash(value.profile_sha256) || !Array.isArray(value.sections) || value.sections.length === 0) invalid()
  const sectionKeys = new Set<string>()
  const fieldKeys = new Set<string>()
  for (const section of value.sections) {
    if (!isRecord(section) || !exactKeys(section, ['section_key', 'display_name', 'fields'])
      || !id(section.section_key) || !text(section.display_name) || !Array.isArray(section.fields)
      || section.fields.length === 0 || sectionKeys.has(section.section_key)) invalid()
    sectionKeys.add(section.section_key)
    for (const field of section.fields) {
      if (!isRecord(field) || !exactKeys(field, ['field_key', 'short_title'])
        || !id(field.field_key) || !text(field.short_title) || fieldKeys.has(field.field_key)) invalid()
      fieldKeys.add(field.field_key)
    }
  }
}

function assertPack(value: unknown): asserts value is SchemaPackDefinition830G3 & RecordValue {
  const keys = ['contract', 'schema_pack_id', 'schema_version', 'display_name', 'entity_type',
    'applicable_classifications', 'workbook_sha256', 'workbook_sheet', 'fields',
    'presentation_profile_ref', 'schema_pack_sha256']
  if (!isRecord(value) || !exactKeys(value, keys) || value.contract !== PACK_CONTRACT
    || !id(value.schema_pack_id) || !id(value.schema_version) || !text(value.display_name, true)
    || value.entity_type !== 'insurance_product' || !Array.isArray(value.applicable_classifications)
    || value.applicable_classifications.length !== 1 || !id(value.applicable_classifications[0])
    || !hash(value.workbook_sha256) || !text(value.workbook_sheet, true) || !Array.isArray(value.fields)
    || value.fields.length === 0 || !isRecord(value.presentation_profile_ref)
    || !exactKeys(value.presentation_profile_ref, ['profile_id', 'profile_version'])
    || !id(value.presentation_profile_ref.profile_id) || !id(value.presentation_profile_ref.profile_version)
    || !hash(value.schema_pack_sha256)) invalid()
  const fieldKeys = new Set<string>()
  for (const field of value.fields) {
    assertField(field)
    if (fieldKeys.has(field.field_key)) invalid()
    fieldKeys.add(field.field_key)
  }
}

async function assertEntryHashes(entry: SchemaPackCatalog830G3['entries'][number]): Promise<void> {
  const pack = entry.pack as SchemaPackDefinition830G3 & RecordValue
  const profile = entry.profile as PresentationProfile830G3 & RecordValue
  const fieldHashes = pack.fields.map(async field => {
    const raw = field as SchemaPackField830G3 & RecordValue
    const metadata = without(without(raw, 'semantic_sha256'), 'source_row')
    const expected = await schemaWikiHash(FIELD_CONTRACT, { schema_pack_id: pack.schema_pack_id, field: metadata })
    if (expected !== field.semantic_sha256) invalid()
  })
  const [expectedPack, expectedProfile] = await Promise.all([
    schemaWikiHash(PACK_CONTRACT, without(pack, 'schema_pack_sha256')),
    schemaWikiHash(PROFILE_CONTRACT, without(profile, 'profile_sha256')),
    ...fieldHashes,
  ])
  if (expectedPack !== pack.schema_pack_sha256 || expectedProfile !== profile.profile_sha256) invalid()
}

function deepFreeze<T>(value: T): T {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value)
    for (const nested of Object.values(value as Record<string, unknown>)) deepFreeze(nested)
  }
  return value
}

export async function parseSchemaPackCatalog830G3(value: unknown): Promise<SchemaPackCatalog830G3> {
  const keys = ['contract', 'catalog_id', 'catalog_version', 'workbook_sha256',
    'mapping_config_sha256', 'entries', 'field_name_union_count',
    'field_name_intersection_count', 'catalog_sha256']
  if (!isRecord(value) || !exactKeys(value, keys) || value.contract !== CATALOG_CONTRACT
    || value.catalog_id !== CATALOG_ID_830_G3 || value.catalog_version !== CATALOG_VERSION_830_G3
    || !hash(value.workbook_sha256) || !hash(value.mapping_config_sha256)
    || !Array.isArray(value.entries) || value.entries.length !== 11
    || !Number.isSafeInteger(value.field_name_union_count) || !Number.isSafeInteger(value.field_name_intersection_count)
    || value.catalog_sha256 !== CATALOG_CONTENT_SHA256_830_G3) invalid()

  const packIDs = new Set<string>()
  const profileIDs = new Set<string>()
  const fieldSets: Set<string>[] = []
  for (const entry of value.entries) {
    if (!isRecord(entry) || !exactKeys(entry, ['pack', 'profile', 'profile_confirmation_status', 'quality_status'])
      || entry.profile_confirmation_status !== 'PENDING_PRODUCT_OWNER_CONFIRMATION'
      || entry.quality_status !== 'REGISTERED_NOT_QUALITY_ADMITTED') invalid()
    assertPack(entry.pack)
    assertProfile(entry.profile)
    const pack = entry.pack
    const profile = entry.profile
    const packIdentity = `${pack.schema_pack_id}\u0000${pack.schema_version}`
    const profileIdentity = `${profile.profile_id}\u0000${profile.profile_version}`
    const packFields = new Set(pack.fields.map(field => field.field_key))
    const profileFields = profile.sections.flatMap(section => section.fields.map(field => field.field_key))
    if (packIDs.has(packIdentity) || profileIDs.has(profileIdentity)
      || pack.workbook_sha256 !== value.workbook_sha256
      || profile.profile_id !== pack.presentation_profile_ref.profile_id
      || profile.profile_version !== pack.presentation_profile_ref.profile_version
      || profile.schema_pack_id !== pack.schema_pack_id || profile.schema_version !== pack.schema_version
      || profile.schema_pack_sha256 !== pack.schema_pack_sha256
      || profileFields.length !== packFields.size || profileFields.some(field => !packFields.has(field))) invalid()
    packIDs.add(packIdentity)
    profileIDs.add(profileIdentity)
    fieldSets.push(packFields)
  }
  const union = new Set(fieldSets.flatMap(set => [...set]))
  const intersection = [...fieldSets[0]].filter(field => fieldSets.every(set => set.has(field)))
  if (union.size !== value.field_name_union_count || intersection.length !== value.field_name_intersection_count) invalid()

  await Promise.all((value.entries as unknown as SchemaPackCatalog830G3['entries']).map(assertEntryHashes))
  const expectedCatalog = await schemaWikiHash(CATALOG_CONTRACT, without(value, 'catalog_sha256'))
  const wireHash = await sha256(JSON.stringify(value))
  if (expectedCatalog !== value.catalog_sha256 || wireHash !== CATALOG_WIRE_SHA256_830_G3) invalid()
  return deepFreeze(value as unknown as SchemaPackCatalog830G3)
}

function unwrap(value: unknown): unknown {
  if (!isRecord(value) || !exactKeys(value, ['success', 'data']) || value.success !== true) invalid()
  return value.data
}

export async function loadSchemaPackCatalogSession830G3(
  wikiKBID: string,
  transport: SchemaWikiReadTransport,
): Promise<SchemaPackCatalogSession830G3> {
  let scope: SchemaWikiScopeV1
  try {
    scope = parseSchemaWikiScope(unwrap(await transport.get(buildSchemaWikiScopeBootstrapPath(wikiKBID))))
  } catch {
    throw new Error('SCHEMA_PACK_CATALOG_830_G3_SCOPE_INVALID')
  }
  if (scope.wiki_kb_id !== wikiKBID) throw new Error('SCHEMA_PACK_CATALOG_830_G3_SCOPE_INVALID')
  const path = buildScopedSchemaWikiPath(scope,
    `/catalogs/${CATALOG_ID_830_G3}/versions/${CATALOG_VERSION_830_G3}`,
    { expectedScope: scope })
  const catalog = await parseSchemaPackCatalog830G3(unwrap(await transport.get(path)))
  return Object.freeze({ scope, catalog })
}

export async function loadSchemaPackCatalog830G3(
  wikiKBID: string,
  transport: SchemaWikiReadTransport,
): Promise<SchemaPackCatalog830G3> {
  return (await loadSchemaPackCatalogSession830G3(wikiKBID, transport)).catalog
}
