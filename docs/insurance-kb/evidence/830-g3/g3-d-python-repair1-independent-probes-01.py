from __future__ import annotations
import importlib, json, hashlib
from copy import deepcopy
from pathlib import Path

ROOT=Path('/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation')
FIX=ROOT/'harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json'
CONF=ROOT/'docs/insurance-kb/evidence/830-g3/profile-user-confirmation.json'
m=importlib.import_module('insurance_harness.knowledge_compiler.batch_concept_compile_830_g3')

def fresh(): return json.loads(FIX.read_bytes())['request']
def rehash_binding(b): b['binding_sha256']=m._batch_sha256(b['contract'],{k:v for k,v in b.items() if k!='binding_sha256'})
def validate(r):
    r['request_sha256']=m._batch_sha256(r['contract'],{k:v for k,v in r.items() if k!='request_sha256'})
    return m.BatchConceptCompileRequest830G3V1.model_validate(r)
def rejected(name,r,reason):
    try: validate(r)
    except ValueError as e:
        assert reason in str(e),(name,str(e))
        print(f'PASS negative {name}: {reason}')
        return
    raise AssertionError(f'{name} accepted')

# Frozen receipt is the actual semantic object and both independently calculated anchors match.
r=fresh(); actual=json.loads(CONF.read_bytes())
assert r['profile_confirmation']['receipt']==actual
assert r['profile_confirmation']['receipt_file_sha256']==hashlib.sha256(CONF.read_bytes()).hexdigest()=='7f6141c63db4a77e3d13a0a8d632ea5463761bedeee7bd1aabef165d68c86863'
assert m._batch_sha256(actual['contract'],actual)=='cd40072b3c4c32c3ed9440c7ff1ff5effc502c506b4ab11c86bbe438c7649b66'
print('PASS positive exact profile receipt/file/semantic')

for field,value in [('actor_display_name','forged-name'),('queue_owner','forged-owner')]:
    r=fresh(); c=r['profile_confirmation']; c['receipt'][field]=value
    c['receipt_semantic_sha256']=m._batch_sha256(c['receipt']['contract'],c['receipt'])
    rejected('profile-'+field,r,'PROFILE_CONFIRMATION_MISMATCH')

for field in ('parser_identity','page_number'):
    r=fresh(); cb=r['resolution_inputs']['corpus']['entries'][0]['blocks'][0]
    bs=next(x for x in r['base_request']['sources'] if (x['revision_id'],x['block_id'])==(cb['revision_id'],cb['block_id']))
    bs[field]=('forged-parser' if field == 'parser_identity' else bs[field]+1)
    rejected('source-full-'+field,r,'SOURCE_CLOSURE_MISMATCH')

r=fresh(); b=next(x for x in r['entity_bindings'] if x['resolution_disposition']=='MATCH')
b['display_name'] += '-forged'; rehash_binding(b)
rejected('match-display-anchor',r,'RESOLUTION_REFERENCE_INVALID')

r=fresh(); b=next(x for x in r['entity_bindings'] if x['resolution_disposition']=='CREATE')
b['entity_key_sha256']='0'*64; rehash_binding(b)
rejected('create-candidate-key',r,'RESOLUTION_REFERENCE_INVALID')

# Positive closure: all selected evidence is the exact child's full ID set and all overlaps are full objects.
obj=validate(fresh()); decision={}
for parent in obj.resolution.decisions:
    for child in parent.children: decision[(parent.material_id,child.proposal_ref)]=child
for b in obj.entity_bindings:
    for ref in b.resolution_refs:
        child=decision[(ref.material_id,ref.proposal_ref)]
        got={x.evidence_id for x in b.resolution_evidence if (x.material_id,x.proposal_ref)==(ref.material_id,ref.proposal_ref)}
        assert got==set(child.evidence_ids)
base={(x.revision_id,x.block_id):x for x in obj.base_request.sources}
corpus={}
for row in obj.resolution_inputs.corpus.entries:
    for block in row.blocks:
        key=(block.revision_id,block.block_id)
        assert key not in corpus or corpus[key]==block
        corpus[key]=block
for key in set(base)&set(corpus): assert base[key]==corpus[key]
print('PASS positive selected-child evidence and full SourceBlock overlap')
print('ALL 8 INDEPENDENT CHECKS PASSED')
