import gzip, hashlib, json
from pathlib import Path
from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as m
R=Path.cwd(); E=R/'docs/insurance-kb/evidence/830-g3'; F=R/'harness/tests/fixtures/batch_concept_compile_830_g3'
def sha(b):return hashlib.sha256(b).hexdigest()
source=R/'harness/src/insurance_harness/knowledge_compiler/batch_concept_compile_830_g3.py'
assert sha(source.read_bytes())=='e8e0dbcd8bf4cb1f2072d6fbf4ebf79f3554cbfef53c9c1f84011dbcc4357316'
raw=(F/'candidate.json').read_bytes();post=(F/'preparation-request.json').read_bytes()
assert sha(raw)=='e7be83db31d987c19a27c213e81b4d4c1f64993766a8b16921c67f90377dd783'
assert sha(post)=='09b64b3e4928173a22dbd6e664abc73903cacbf7735eb0f8292d3366f50ecbc4'
assert len(post)==2254490 and len(post)<8388608
value=json.loads(raw); req=value['request']; base=req['base_request']
assert json.loads(post)['batch_concept_candidate_bundle']==value
old=json.loads(gzip.decompress((E/'d-repair1-snapshots/candidate.json.gz').read_bytes()))['request']['base_request']
for k in ['existing_fields','existing_definitions','existing_pages','existing_entity_versions','base_release_id','base_activation_epoch']:
 assert base[k]==old[k], k
actual_path=R/'docs/insurance-kb/evidence/830-g2/b-source-complete-candidate-bundle.json'
actual_bytes=actual_path.read_bytes();assert sha(actual_bytes)=='69dd25e29ea771a512cf24c083a52e8347386def68b30d90d379f2b0dfe181d1'
actual=json.loads(actual_bytes)['compile_result']['output']
for a,b in [('existing_fields','fields'),('existing_definitions','definitions'),('existing_pages','pages')]:
 assert base[a]==actual[b],a
identity_keys={(x['evidence']['revision_id'],x['evidence']['block_id']) for binding in req['entity_bindings'] for x in binding['resolution_evidence']}
corpus_keys={(x['revision_id'],x['block_id']) for row in req['resolution_inputs']['corpus']['entries'] for x in row['blocks']}
field_keys={(e['revision_id'],e['block_id']) for f in value['model_compile_result']['output']['fields'] for e in f['evidence']}
nonidentity_field=field_keys & corpus_keys - identity_keys
assert len(nonidentity_field)==1
for section in ['model_compile_result','compile_result','review_result']:
 ex=value[section]['execution'];assert sha(ex['raw_output'].encode())==ex['raw_output_hash']
assert len({value[k]['execution']['raw_output_hash'] for k in ['model_compile_result','compile_result','review_result']})==3
bundle=m.validate_batch_candidate(raw)
assert len(bundle.request.base_request.existing_fields)==134
assert len(bundle.model_compile_result.output.fields)==208
assert len(bundle.compile_result.output.fields)==342
assert len(bundle.request.base_request.sources)==27
assert sha(source.read_bytes())=='e8e0dbcd8bf4cb1f2072d6fbf4ebf79f3554cbfef53c9c1f84011dbcc4357316'
print(json.dumps({'status':'PASS','canonical_candidate_valid':True,'exact_actual_g2_base_preserved':True,'base_fields':134,'delta_fields':208,'final_fields':342,'sources':27,'nonidentity_field_source_keys':sorted(nonidentity_field),'distinct_actual_fixture_raw_hashes':3,'post_bytes':len(post),'post_limit_bytes':8388608,'provider':0,'database':0,'build':0},ensure_ascii=False,indent=2))
