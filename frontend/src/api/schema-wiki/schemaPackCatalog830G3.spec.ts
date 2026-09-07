import { readFileSync } from 'node:fs'

import { describe, expect, it, vi } from 'vitest'

import {
  CATALOG_ID_830_G3,
  CATALOG_VERSION_830_G3,
  loadSchemaPackCatalog830G3,
} from './schemaPackCatalog830G3.ts'

const vector = JSON.parse(readFileSync(new URL(
  '../../../../internal/handler/schema_pack_catalog_830_g3.generated.json',
  import.meta.url,
), 'utf8'))

const scope = Object.freeze({
  version: 'schema-wiki-scope.v1',
  space_id: 'space-g3',
  raw_kb_id: 'raw-g3',
  wiki_kb_id: 'wiki-g3',
  scope_sha256: 'a'.repeat(64),
})

function transportFor(catalog: unknown) {
  return { get: vi.fn()
    .mockResolvedValueOnce({ success: true, data: scope })
    .mockResolvedValueOnce({ success: true, data: catalog }) }
}

describe('schema pack catalog 830 G3 API', () => {
  it('bootstraps the exact scope then validates all 11 packs and 801 fields', async () => {
    const transport = transportFor(vector)

    const catalog = await loadSchemaPackCatalog830G3('wiki-g3', transport)

    expect(catalog.catalog_id).toBe(CATALOG_ID_830_G3)
    expect(catalog.catalog_version).toBe(CATALOG_VERSION_830_G3)
    expect(catalog.entries).toHaveLength(11)
    expect(catalog.entries.flatMap(entry => entry.pack.fields)).toHaveLength(801)
    expect(new Set(catalog.entries.map(entry => entry.profile.sections.length))).toEqual(new Set([7, 8]))
    expect(transport.get.mock.calls).toEqual([
      ['/api/v1/knowledgebase/wiki-g3/wiki/schema-scope'],
      ['/api/v1/knowledgebase/wiki-g3/wiki/release-scopes/space-g3/raw/raw-g3/schema/catalogs/'
        + `${CATALOG_ID_830_G3}/versions/${CATALOG_VERSION_830_G3}`],
    ])
  })

  it.each([
    ['catalog hash', (copy: any) => { copy.catalog_sha256 = '0'.repeat(64) }],
    ['field metadata', (copy: any) => { copy.entries[0].pack.fields[0].description += 'tamper' }],
    ['field semantic hash', (copy: any) => { copy.entries[0].pack.fields[0].semantic_sha256 = '0'.repeat(64) }],
    ['pack hash', (copy: any) => { copy.entries[0].pack.schema_pack_sha256 = '0'.repeat(64) }],
    ['profile hash', (copy: any) => { copy.entries[0].profile.profile_sha256 = '0'.repeat(64) }],
    ['profile binding', (copy: any) => { copy.entries[0].profile.schema_pack_id = 'other-pack' }],
    ['profile topology', (copy: any) => { copy.entries[0].profile.sections[0].fields.push(copy.entries[0].profile.sections[0].fields[0]) }],
    ['confirmation status', (copy: any) => { copy.entries[0].profile_confirmation_status = 'APPROVED' }],
    ['quality status', (copy: any) => { copy.entries[0].quality_status = 'QUALITY_ADMITTED' }],
    ['integer metadata', (copy: any) => { copy.entries[0].pack.fields[0].usage_frequency = 11.5 }],
    ['unknown property', (copy: any) => { copy.entries[0].pack.fields[0].invented = true }],
  ])('rejects %s tampering', async (_name, mutate) => {
    const copy = structuredClone(vector)
    mutate(copy)
    await expect(loadSchemaPackCatalog830G3('wiki-g3', transportFor(copy)))
      .rejects.toThrow('SCHEMA_PACK_CATALOG_830_G3_INVALID')
  })

  it('rejects scope drift and never requests the catalog', async () => {
    const get = vi.fn().mockResolvedValue({ success: true, data: { ...scope, wiki_kb_id: 'other' } })
    await expect(loadSchemaPackCatalog830G3('wiki-g3', { get }))
      .rejects.toThrow('SCHEMA_PACK_CATALOG_830_G3_SCOPE_INVALID')
    expect(get).toHaveBeenCalledTimes(1)
  })
})
