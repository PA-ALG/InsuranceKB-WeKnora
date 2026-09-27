from pathlib import Path
import hashlib,json
from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_sha256_830_g3
root=Path('/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation')
before=json.loads(Path('/private/tmp/g3-d-root-interop-production-before-02.json').read_text())
for path,expected in before.items():
    assert hashlib.sha256((root/path).read_bytes()).hexdigest()==expected,path
assert hashlib.sha256((root/'frontend/src/api/schema-wiki/batchConcept830G3.ts').read_bytes()).hexdigest()=='52ec691d36c0984c60725ff9b8f6ed08de8c5f47817a1ca7f1a4b63075192b05'
results=[]
for state in ['draft','ready']:
    old=json.loads(Path(f'/private/tmp/g3-d-root-service-json-01/{state}.json').read_text())['data']
    path=Path(f'/private/tmp/g3-d-root-service-json-02/{state}.json');raw=path.read_bytes();new=json.loads(raw)['data']
    assert len(new)==13
    old_hash=old.pop('read_sha256');claimed=new.pop('read_sha256')
    assert old==new,'Unexpected logical content change'
    expected=batch_sha256_830_g3('batch-concept-preparation-read.830.g3.v1',new)
    assert claimed==expected
    logical=json.dumps(new,ensure_ascii=False)
    assert logical.count('\u2028')==28
    results.append(dict(status=state.upper(),file_sha256=hashlib.sha256(raw).hexdigest(),old_read_sha256=old_hash,claimed_read_sha256=claimed,frozen_python_read_sha256=expected,equal=True,logical_response_changed_only_read_sha256=True,u2028_count=28))
print(json.dumps(dict(contract='830-g3-d-repair1-root-frozen-python-read-hash.v1',status='PASS',production_source_sha256=before,results=results,effects=dict(provider=0,database=0,live_http=0,build=0,deployment=0)),indent=2))
