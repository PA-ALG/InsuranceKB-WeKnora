import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { bootstrapSchemaWikiClient } from '../../../api/schema-wiki/index.ts'
import {
  parseSchemaPack,
  parseSchemaWikiCurrentEntityVersion,
  parseSchemaWikiScope,
} from './schemaWikiContract.ts'
import {
  assertStableTaxonomyReparent,
  buildPinnedSchemaWikiReleasePath,
  buildScopedSchemaWikiPath,
  projectSchemaWikiNavigation,
  resolveKnowledgeBaseDefaultTab,
} from './schemaWikiNavigation.ts'

const H = (character: string) => character.repeat(64)
const vector = JSON.parse(readFileSync(new URL(
  '../../../../../internal/application/service/testdata/schema_wiki_contract_vector.json',
  import.meta.url,
), 'utf8')) as { schema_pack: Record<string, unknown> }

function currentEntityVersion() {
  return {
    version: 'schema-wiki-current-entity-version.v1',
    entity_id: 'entity-596-1',
    entity_version_id: 'entity-version-596-1',
    active_release_id: 'release-596-1-active',
    activation_epoch: 4,
    root: {
      contract: 'schema-root-page.v1',
      domain_id: 'medical-insurance',
      domain_sha256: H('1'),
      schema_pack_id: 'medical-596-1-schema67',
      schema_version: '67',
      schema_pack_sha256: H('2'),
      entity_id: 'entity-596-1',
      entity_version_id: 'entity-version-596-1',
      product_version_id: 'product-version-596-1',
      taxonomy_version: 'taxonomy-596-1-v1',
      taxonomy_sha256: H('3'),
      product_display_name: '平安e生保医疗险',
      ordered_section_ids: ['identity', 'coverage'],
      root_page_sha256: H('4'),
    },
  }
}

function loadMedicalReleaseVector(): Record<string, unknown> {
  return JSON.parse(readFileSync(new URL(
    '../../../../../internal/application/service/testdata/schema_wiki_release_596_1_vector.json',
    import.meta.url,
  ), 'utf8')) as Record<string, unknown>
}

test('a Wiki-enabled knowledge base defaults to Schema Wiki without falling back to materials', () => {
  assert.equal(resolveKnowledgeBaseDefaultTab({ wikiEnabled: true }), 'schema')
  assert.equal(resolveKnowledgeBaseDefaultTab({ wikiEnabled: false }), 'documents')
  assert.equal(resolveKnowledgeBaseDefaultTab({ wikiEnabled: true, requestedTab: 'materials' }), 'materials')
})

test('domain and section navigation is produced from validated configuration', () => {
  const schemaPack = parseSchemaPack(structuredClone(vector.schema_pack))
  const navigation = projectSchemaWikiNavigation({
    domains: [{
      domain_id: 'configured-domain',
      display_name: 'Configured Domain',
      ordinal: 3,
    }],
    taxonomy: {
      nodes: [{
        node_id: 'category-configured',
        parent_id: null,
        kind: 'category',
        display_name: 'Configured Category',
        ordinal: 0,
      }],
    },
    schemaPack,
  })

  assert.deepEqual(navigation.domains.map(item => item.domain_id), ['configured-domain'])
  assert.deepEqual(navigation.sections.map(item => item.section_id), ['section-a', 'section-b'])
  assert.throws(() => projectSchemaWikiNavigation({
    domains: navigation.domains.map(item => ({ ...item })),
    taxonomy: { nodes: [] },
    schemaPack: {
      ...schemaPack,
      sections: [{ display_name: 'Broken', section_id: 'broken', ordered_field_ids: ['field-a', 'field-a'] }],
    },
  }), { message: 'SCHEMA_PACK_TOPOLOGY_INVALID' })
})

test('the medical navigation is projected from the frozen pack and taxonomy rather than UI constants', () => {
  const release = loadMedicalReleaseVector()
  const domain = release.domain as Record<string, unknown>
  const taxonomy = release.taxonomy as { nodes: Array<Record<string, unknown>> }
  const pack = parseSchemaPack(release.schema_pack)
  const navigation = projectSchemaWikiNavigation({
    domains: [{
      domain_id: domain.domain_id as string,
      display_name: domain.display_name as string,
      ordinal: 0,
    }],
    taxonomy,
    schemaPack: pack,
  })

  assert.deepEqual(
    navigation.sections.map(section => section.section_id),
    pack.sections.map(section => section.section_id),
  )
  assert.deepEqual(
    navigation.fields.map(field => field.field_id),
    pack.ordered_field_ids,
  )
  assert.equal(navigation.sections.length, 7)
  assert.equal(navigation.fields.length, 67)
})

test('taxonomy reparent changes navigation only and preserves stable authority identities', () => {
  const before = {
    entity_id: 'entity-pingan-eshengbao',
    version_id: 'product-version-596-1',
    field_id: 'product_name',
    citation_id: 'citation-page-12',
    parent_node_id: 'category-old',
    display_path: ['产品', '医疗险'],
  }
  const after = {
    ...before,
    parent_node_id: 'category-new',
    display_path: ['保险产品', '医疗保障'],
  }

  assert.doesNotThrow(() => assertStableTaxonomyReparent(before, after))
  assert.throws(() => assertStableTaxonomyReparent(before, {
    ...after,
    field_id: 'replacement-field',
  }), { message: 'TAXONOMY_REPARENT_AUTHORITY_DRIFT' })
})

test('all Schema paths are derived from one bootstrapped scope', () => {
  const scope = parseSchemaWikiScope({
    version: 'schema-wiki-scope.v1',
    space_id: 'space-1',
    raw_kb_id: 'raw-1',
    wiki_kb_id: 'wiki-1',
    scope_sha256: H('4'),
  })
  assert.equal(
    buildScopedSchemaWikiPath(scope, '/entities/entity-1/versions/version-1/current'),
    '/api/v1/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/schema/entities/entity-1/versions/version-1/current',
  )
  assert.throws(() => buildScopedSchemaWikiPath({ ...scope, raw_kb_id: 'raw-foreign' }, '/domains', {
    expectedScope: scope,
  }), { message: 'SCHEMA_WIKI_SCOPE_DRIFT' })
  assert.throws(() => buildScopedSchemaWikiPath({ ...scope }, '/domains'), {
    message: 'SCHEMA_WIKI_SCOPE_INVALID',
  })
})

test('release member paths use only the validated current response release pin', () => {
  const scope = parseSchemaWikiScope({
    version: 'schema-wiki-scope.v1',
    space_id: 'space-1',
    raw_kb_id: 'raw-1',
    wiki_kb_id: 'wiki-1',
    scope_sha256: H('4'),
  })
  const current = parseSchemaWikiCurrentEntityVersion(currentEntityVersion(), {
    entityId: 'entity-596-1',
    entityVersionId: 'entity-version-596-1',
  })

  assert.equal(
    buildPinnedSchemaWikiReleasePath(scope, current, '/fields/product_name'),
    '/api/v1/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/schema'
      + '/releases/release-596-1-active/fields/product_name',
  )
  assert.throws(() => buildPinnedSchemaWikiReleasePath(
    scope,
    { ...current, active_release_id: 'release-caller-selected' },
    '/root',
  ), { message: 'SCHEMA_WIKI_CURRENT_ENTITY_VERSION_INVALID' })
  assert.throws(() => buildPinnedSchemaWikiReleasePath(scope, scope as never, '/root'), {
    message: 'SCHEMA_WIKI_CURRENT_ENTITY_VERSION_INVALID',
  })
  assert.throws(() => buildPinnedSchemaWikiReleasePath(
    scope,
    current,
    '/releases/latest/root',
  ), { message: 'SCHEMA_WIKI_RELEASE_MEMBER_PATH_INVALID' })
})

test('the API client bootstraps Wiki scope before any scoped Schema request', async () => {
  const calls: string[] = []
  const transport = {
    async get(path: string): Promise<unknown> {
      calls.push(path)
      if (calls.length === 1) {
        return {
          version: 'schema-wiki-scope.v1',
          space_id: 'space-1',
          raw_kb_id: 'raw-1',
          wiki_kb_id: 'wiki-1',
          scope_sha256: H('4'),
        }
      }
      return { domains: [] }
    },
  }

  const client = await bootstrapSchemaWikiClient('wiki-1', transport)
  await client.getDomains()

  assert.deepEqual(calls, [
    '/api/v1/knowledgebase/wiki-1/wiki/schema-scope',
    '/api/v1/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/schema/domains',
  ])
})

test('a foreign bootstrap scope is rejected before any scoped Schema request', async () => {
  const calls: string[] = []
  const transport = {
    async get(path: string): Promise<unknown> {
      calls.push(path)
      return {
        version: 'schema-wiki-scope.v1',
        space_id: 'space-1',
        raw_kb_id: 'raw-1',
        wiki_kb_id: 'wiki-foreign',
        scope_sha256: H('4'),
      }
    },
  }

  await assert.rejects(() => bootstrapSchemaWikiClient('wiki-1', transport), {
    message: 'SCHEMA_WIKI_SCOPE_DRIFT',
  })
  assert.deepEqual(calls, ['/api/v1/knowledgebase/wiki-1/wiki/schema-scope'])
})
