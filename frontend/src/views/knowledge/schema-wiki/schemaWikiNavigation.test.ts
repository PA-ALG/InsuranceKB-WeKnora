import assert from 'node:assert/strict'
import test from 'node:test'

import { bootstrapSchemaWikiClient } from '../../../api/schema-wiki/index.ts'
import {
  assertStableTaxonomyReparent,
  buildScopedSchemaWikiPath,
  projectSchemaWikiNavigation,
  resolveKnowledgeBaseDefaultTab,
} from './schemaWikiNavigation.ts'

const H = (character: string) => character.repeat(64)

test('a Wiki-enabled knowledge base defaults to Schema Wiki without falling back to materials', () => {
  assert.equal(resolveKnowledgeBaseDefaultTab({ wikiEnabled: true }), 'schema')
  assert.equal(resolveKnowledgeBaseDefaultTab({ wikiEnabled: false }), 'documents')
  assert.equal(resolveKnowledgeBaseDefaultTab({ wikiEnabled: true, requestedTab: 'materials' }), 'materials')
})

test('domain and section navigation is produced from validated configuration', () => {
  const navigation = projectSchemaWikiNavigation({
    domains: [{
      domain_id: 'configured-domain',
      display_name: 'Configured Domain',
      ordinal: 3,
    }],
    taxonomy: {
      version: 'active-taxonomy.v1',
      taxonomy_sha256: H('3'),
      nodes: [{
        node_id: 'category-configured',
        parent_id: null,
        kind: 'category',
        display_name: 'Configured Category',
        ordinal: 0,
      }],
    },
    schemaPack: {
      schema_pack_id: 'configured-pack.v1',
      sections: [{ section_id: 'configured-section', ordinal: 0, field_ids: ['configured-field'] }],
      fields: [{ field_id: 'configured-field', ordinal: 0 }],
    },
  })

  assert.deepEqual(navigation.domains.map(item => item.domain_id), ['configured-domain'])
  assert.deepEqual(navigation.sections.map(item => item.section_id), ['configured-section'])
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
  const scope = {
    space_id: 'space-1',
    raw_kb_id: 'raw-1',
    wiki_kb_id: 'wiki-1',
    scope_sha256: H('4'),
  }
  assert.equal(
    buildScopedSchemaWikiPath(scope, '/entities/entity-1/versions/version-1/current'),
    '/api/v1/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/schema/entities/entity-1/versions/version-1/current',
  )
  assert.throws(() => buildScopedSchemaWikiPath({ ...scope, raw_kb_id: 'raw-foreign' }, '/domains', {
    expectedScope: scope,
  }), { message: 'SCHEMA_WIKI_SCOPE_DRIFT' })
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
