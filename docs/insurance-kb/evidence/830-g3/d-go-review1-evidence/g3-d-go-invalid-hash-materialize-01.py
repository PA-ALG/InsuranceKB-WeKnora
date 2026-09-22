from pathlib import Path
import json,hashlib
from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as d
from insurance_harness.knowledge_compiler import batch_entity_resolution_830_g3 as c
from insurance_harness.knowledge_compiler import concept_free_wiki_830_g2 as g2
ROOT=Path('/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation'); SRC=ROOT/'harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json'; OUT=Path('/private/tmp/g3-d-go-invalid-native-capture-hash-01.json')
b=json.loads(SRC.read_bytes()); req=b['request']; inp=req['resolution_inputs']; corpus=inp['corpus']; props=inp['proposals']; res=req['resolution']
entry=corpus['entries'][0]; entry['native_capture_sha256']='not-a-sha256'; entry['entry_sha256']=c._batch_sha256('corpus-entry.830.g3.v1',{k:v for k,v in entry.items() if k!='entry_sha256'})
corpus['corpus_sha256']=c._batch_sha256(corpus['contract'],{k:v for k,v in corpus.items() if k!='corpus_sha256'})
props['corpus_sha256']=corpus['corpus_sha256']
entry_sha_by_id={x['material_id']:x['entry_sha256'] for x in corpus['entries']}
for p in props['proposals']:
 p['corpus_entry_sha256']=entry_sha_by_id[p['material_id']]
 p['proposal_sha256']=c._batch_sha256('material-proposal.830.g3.v1',{k:v for k,v in p.items() if k!='proposal_sha256'})
for receipt in props['model_receipts']:
 for mb in receipt['material_bindings']: mb['corpus_entry_sha256']=entry_sha_by_id[mb['material_id']]
 receipt['input_sha256']=c._batch_sha256('batch-classifier-input.830.g3.v1',{'corpus_sha256':corpus['corpus_sha256'],'material_bindings':receipt['material_bindings']})
props['proposals_sha256']=c._batch_sha256(props['contract'],{k:v for k,v in props.items() if k!='proposals_sha256'})
res['corpus_sha256']=corpus['corpus_sha256']; res['proposals_sha256']=props['proposals_sha256']; res['batch_sha256']=c._batch_sha256(res['contract'],{k:v for k,v in res.items() if k!='batch_sha256'})
inp['inputs_sha256']=d._batch_sha256(inp['contract'],{k:v for k,v in inp.items() if k!='inputs_sha256'})
req['request_sha256']=d._batch_sha256(req['contract'],{k:v for k,v in req.items() if k!='request_sha256'})
base_hash=g2.digest('compile-request',req['base_request']); model=b['model_compile_result']; model['execution']['context_hash']=d._batch_sha256('batch-concept-compile-context.830.g3.v1',{'request':req,'request_sha256':req['request_sha256'],'base_request_hash':base_hash,'output_mode':'NEW_MEMBERS_ONLY'})
model_exec_sha=d._batch_sha256('batch-concept-model-execution.830.g3.v1',model['execution']); model_output_hash=g2.digest('compile-output',model['output']); final=b['compile_result']; final['execution']['context_hash']=d._batch_sha256('batch-concept-carry-context.830.g3.v1',{'request_sha256':req['request_sha256'],'model_compile_output_hash':model_output_hash,'model_compile_execution_sha256':model_exec_sha}); final_hash=g2.digest('compile-output',final['output']); review=b['review_result']; review['execution']['context_hash']=d._batch_sha256('batch-concept-review-context.830.g3.v1',{'request':req,'candidate':final['output'],'request_sha256':req['request_sha256'],'base_request_hash':base_hash,'output_hash':final_hash}); b['candidate_hash']=d._batch_sha256(b['contract'],{k:v for k,v in b.items() if k!='candidate_hash'})
raw=d._canonical_json(b).encode(); OUT.write_bytes(raw)
try: d.validate_batch_candidate(raw); py='ACCEPTED_UNEXPECTEDLY'
except Exception as e: py=type(e).__name__+':'+str(e).splitlines()[0]
print(json.dumps({'path':str(OUT),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'python':py}))
