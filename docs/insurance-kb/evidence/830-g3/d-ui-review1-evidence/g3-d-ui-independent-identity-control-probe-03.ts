import { readFileSync } from 'node:fs'
import { parseBatchConceptPreparation830G3 } from '/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/frontend/src/api/schema-wiki/batchConcept830G3.ts'
import { parseSchemaPackCatalog830G3 } from '/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/frontend/src/api/schema-wiki/schemaPackCatalog830G3.ts'
import { parseSchemaWikiScope } from '/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/frontend/src/views/knowledge/schema-wiki/schemaWikiContract.ts'
const path='/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json'
const candidate=JSON.parse(readFileSync(path,'utf8')); const base=candidate.request.base_request
const scope=parseSchemaWikiScope({version:'schema-wiki-scope.v1',space_id:base.space_id,raw_kb_id:base.raw_kb_id,wiki_kb_id:base.wiki_kb_id,scope_sha256:'7'.repeat(64)})
const enc=new TextEncoder()
function canonical(v:any):string{if(v===null||typeof v==='boolean'||typeof v==='string'||typeof v==='number')return JSON.stringify(v);if(Array.isArray(v))return `[${v.map(canonical).join(',')}]`;return `{${Object.keys(v).sort().map(k=>`${JSON.stringify(k)}:${canonical(v[k])}`).join(',')}}`}
async function sha(s:string){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',enc.encode(s)))].map(x=>x.toString(16).padStart(2,'0')).join('')}
async function dh(c:string,v:any){return sha(`schema-wiki-canonical.v1\0${c}\0${canonical(v)}`)}
async function response(){const v:any={contract:'batch-concept-preparation-read.830.g3.v1',read_mode:'preparation',tenant_id:base.tenant_id,space_id:base.space_id,raw_kb_id:base.raw_kb_id,wiki_kb_id:base.wiki_kb_id,preparation_id:'preparation-g3',status:'DRAFT',candidate_sha256:candidate.candidate_hash,expected_base_release_id:base.base_release_id,expected_base_activation_epoch:base.base_activation_epoch,page_manifest:structuredClone(candidate.page_manifest),read_sha256:''};v.read_sha256=await dh(v.contract,Object.fromEntries(Object.entries(v).filter(([k])=>k!=='read_sha256')));return v}
async function main(){
const catalog=await parseSchemaPackCatalog830G3(structuredClone(candidate.request.catalog))
const good=await response(); await parseBatchConceptPreparation830G3(good,scope,catalog,'preparation-g3')
const attacked=await response(); const member=attacked.page_manifest.members.find((m:any)=>Array.isArray(m.payload?.evidence)&&m.payload.evidence.length); const before=member.payload.evidence[0].parser_identity; member.payload.evidence[0].parser_identity='parser\nidentity'; attacked.page_manifest.members_sha256=await dh('batch-concept-page-members.830.g3.v1',{members:attacked.page_manifest.members}); attacked.read_sha256=await dh(attacked.contract,Object.fromEntries(Object.entries(attacked).filter(([k])=>k!=='read_sha256')))
let result='REJECTED'; try{await parseBatchConceptPreparation830G3(attacked,scope,catalog,'preparation-g3');result='ACCEPTED'}catch(e){result='REJECTED:'+String(e)}
console.log(JSON.stringify({positive:'ACCEPTED',attack:'internal-LF in Evidence.parser_identity',before,result,manifest_sha256:attacked.page_manifest.members_sha256,read_sha256:attacked.read_sha256},null,2))

}
main().catch(e=>{console.error(e);process.exitCode=1})
