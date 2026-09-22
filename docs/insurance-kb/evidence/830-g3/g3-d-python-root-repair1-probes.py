import copy
import hashlib
import json
import sys
from pathlib import Path
from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as m
root = Path.cwd()
source = root / 'harness/src/insurance_harness/knowledge_compiler/batch_concept_compile_830_g3.py'
assert hashlib.sha256(source.read_bytes()).hexdigest() == sys.argv[1]
fixture = root / 'harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json'
raw = fixture.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '179affc52b282ea16d3aecfda091c449de3d62992c4f5b337bb97609df414de0'
bundle = m.validate_batch_candidate(raw)
assert len(bundle.compile_result.output.fields) == 342
base = bundle.request.model_dump(mode='json')
def rehash(obj, field):
    obj[field] = m._batch_sha256(obj['contract'], {k:v for k,v in obj.items() if k != field})
def reject(name, value, reason):
    rehash(value, 'request_sha256')
    try:
        m.BatchConceptCompileRequest830G3V1.model_validate(value)
    except ValueError as exc:
        assert reason in str(exc), (name, str(exc))
        print('PASS', name, reason)
    else:
        raise AssertionError('accepted: ' + name)
for field in ['entity_key_sha256', 'version_candidate_key_sha256']:
    value = copy.deepcopy(base)
    binding = next(b for b in value['entity_bindings'] if b['resolution_disposition'] == 'MATCH')
    binding[field] = '0' * 64
    rehash(binding, 'binding_sha256')
    reject('MATCH-'+field, value, 'RESOLUTION_REFERENCE_INVALID')
value = copy.deepcopy(base)
confirmation = value['profile_confirmation']
confirmation['receipt']['actor_display_name'] = 'fabricated display name'
confirmation['receipt_semantic_sha256'] = m._batch_sha256(confirmation['receipt']['contract'], confirmation['receipt'])
reject('profile-display-name-rehashed', value, 'PROFILE_CONFIRMATION_MISMATCH')
value = copy.deepcopy(base)
value['base_request']['sources'][0]['parser_identity'] += '-TAMPER'
reject('same-source-parser-identity-drift', value, 'SOURCE_CLOSURE_MISMATCH')
assert hashlib.sha256(source.read_bytes()).hexdigest() == sys.argv[1]
print(json.dumps({'baseline_fields':342,'additional_attacks_rejected':4,'provider':0,'database':0,'build':0}))
