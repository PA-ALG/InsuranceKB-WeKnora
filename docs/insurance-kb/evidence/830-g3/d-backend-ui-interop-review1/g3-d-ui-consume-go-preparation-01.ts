import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import assert from 'node:assert/strict'
import { parseBatchConceptPreparation830G3 } from '/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/frontend/src/api/schema-wiki/batchConcept830G3.ts'
import { parseSchemaPackCatalog830G3 } from '/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/frontend/src/api/schema-wiki/schemaPackCatalog830G3.ts'
import { parseSchemaWikiScope } from '/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/frontend/src/views/knowledge/schema-wiki/schemaWikiContract.ts'

// Local protocol integration only. This fixture scope is not live authorization.
async function main() {
  const [inputPath, expectedPreparationID, expectedStatus] = process.argv.slice(2)
  assert(inputPath && expectedPreparationID && ['DRAFT', 'READY'].includes(expectedStatus))
  const candidateBytes = readFileSync('/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json')
  assert.equal(createHash('sha256').update(candidateBytes).digest('hex'), 'e7be83db31d987c19a27c213e81b4d4c1f64993766a8b16921c67f90377dd783')
  const candidate = JSON.parse(candidateBytes.toString('utf8'))
  const base = candidate.request.base_request
  const scope = parseSchemaWikiScope({ version: 'schema-wiki-scope.v1', space_id: base.space_id, raw_kb_id: base.raw_kb_id, wiki_kb_id: base.wiki_kb_id, scope_sha256: '7'.repeat(64) })
  const catalog = await parseSchemaPackCatalog830G3(structuredClone(candidate.request.catalog))
  const bytes = readFileSync(inputPath)
  const wire = JSON.parse(bytes.toString('utf8'))
  assert.deepEqual(Object.keys(wire).sort(), ['data', 'success'])
  assert.equal(wire.success, true)
  assert.equal(wire.data.candidate_sha256, candidate.candidate_hash)
  assert.equal(wire.data.expected_base_release_id, base.base_release_id)
  assert.equal(wire.data.expected_base_activation_epoch, base.base_activation_epoch)
  const parsed = await parseBatchConceptPreparation830G3(wire.data, scope, catalog, expectedPreparationID)
  assert.equal(parsed.status, expectedStatus)
  assert.equal(parsed.entities.length, 5)
  assert.equal(parsed.members.filter(member => member.kind === 'field_assertion').length, 342)
  console.log(JSON.stringify({ contract: '830-g3-go-http-to-frozen-ui-parser-check.v1', status: 'PASS', input_path: inputPath, input_sha256: createHash('sha256').update(bytes).digest('hex'), input_bytes: bytes.length, preparation_id: expectedPreparationID, preparation_status: parsed.status, candidate_sha256: parsed.candidateHash, entities: parsed.entities.length, fields: 342, boundary: 'Synthetic protocol test response; no HTTP server, live scope, DB, provider, browser or deployment.' }, null, 2))
}
main().catch(error => { console.error(error); process.exitCode = 1 })
