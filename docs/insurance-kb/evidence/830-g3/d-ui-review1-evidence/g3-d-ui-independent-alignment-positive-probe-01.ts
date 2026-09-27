import { readFileSync } from 'node:fs'
import { loadBatchConceptPreparation830G3 } from '/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/frontend/src/api/schema-wiki/batchConcept830G3.ts'
const root='/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation'
const candidate=JSON.parse(readFileSync(root+'/harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json','utf8')); const old=JSON.parse(readFileSync(root+'/docs/insurance-kb/evidence/830-g2/b-source-complete-candidate-bundle.json','utf8')); const base=candidate.request.base_request; const enc=new TextEncoder()
function canonical(v:any):string{if(v===null||typeof v==='boolean'||typeof v==='string'||typeof v==='number')return JSON.stringify(v);if(Array.isArray(v))return `[${v.map(canonical).join(',')}]`;return `{${Object.keys(v).sort().map(k=>`${JSON.stringify(k)}:${canonical(v[k])}`).join(',')}}`}
async function sha(s:string){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',enc.encode(s)))].map(x=>x.toString(16).padStart(2,'0')).join('')}
async function dh(c:string,v:any){return sha(`schema-wiki-canonical.v1\0${c}\0${canonical(v)}`)}
async function main(){
 const scope={version:'schema-wiki-scope.v1',space_id:base.space_id,raw_kb_id:base.raw_kb_id,wiki_kb_id:base.wiki_kb_id,scope_sha256:'7'.repeat(64)}
 const response:any={contract:'batch-concept-preparation-read.830.g3.v1',read_mode:'preparation',tenant_id:base.tenant_id,space_id:base.space_id,raw_kb_id:base.raw_kb_id,wiki_kb_id:base.wiki_kb_id,preparation_id:'preparation-g3',status:'DRAFT',candidate_sha256:candidate.candidate_hash,expected_base_release_id:base.base_release_id,expected_base_activation_epoch:base.base_activation_epoch,page_manifest:structuredClone(candidate.page_manifest),read_sha256:''}
 response.read_sha256=await dh(response.contract,Object.fromEntries(Object.entries(response).filter(([k])=>k!=='read_sha256')))
 const oldRows=await Promise.all(old.page_manifest.members.map(async(m:any)=>({kind:m.kind,logical_slug:m.member_id,revision_id:old.candidate_hash,member_digest:await dh('concept-page-member.830.g2.v1',m),title:m.title,content:m.content,payload:m.payload})))
 const calls:string[]=[]; const get=async(path:string)=>{calls.push(path);if(path.includes('/wiki/preparations/preparation-g3/schema-scope'))return {success:true,data:scope};if(path.includes('/catalogs/'))return {success:true,data:candidate.request.catalog};if(path.endsWith('/schema/preparations/preparation-g3/batch-concept'))return {success:true,data:response};if(path.endsWith(`/releases/${base.base_release_id}/search?q=`))return {success:true,data:oldRows};throw new Error('unexpected '+path)}
 const result=await loadBatchConceptPreparation830G3(base.wiki_kb_id,'preparation-g3',{get});console.log(JSON.stringify({status:'PASS',alignment_count:result.alignments.length,alignments:result.alignments,calls,called_current:calls.some(x=>x.endsWith('/current')),old_payload_source_sha256:await sha(JSON.stringify(old.page_manifest.members))},null,2))
}
main().catch(e=>{console.error(e);process.exitCode=1})
