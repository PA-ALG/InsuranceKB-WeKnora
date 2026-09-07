#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

SOURCE = Path('/private/tmp/g3-go-c-semantics-oracle-01.py')
REPORT = Path('/private/tmp/g3-go-c-semantics-oracle-01.json')
DEST = Path('/private/tmp/g3-go-c-semantics-cases-01')

# Load definitions only. The 01 script/report are never executed or rewritten.
source_text = SOURCE.read_text(encoding='utf-8')
marker = "base = json.loads(FIXTURE.read_bytes())\n"
if source_text.count(marker) != 1:
    raise SystemExit('ORACLE_SOURCE_LAYOUT_DRIFT')
exec(compile(source_text.split(marker, 1)[0], str(SOURCE), 'exec'), globals())

expected_report = json.loads(REPORT.read_bytes())
expected_by_name = {row['name']: row for row in expected_report['vectors']}
base = json.loads(FIXTURE.read_bytes())
control = d.validate_batch_candidate(FIXTURE.read_bytes())
control_replay = c.resolve_batch(
    catalog=control.request.catalog,
    corpus=control.request.resolution_inputs.corpus,
    proposals=control.request.resolution_inputs.proposals,
    existing_entities=control.request.resolution_inputs.existing_entities,
    policy=control.request.resolution_inputs.policy,
)
if control_replay != control.request.resolution:
    raise SystemExit('POSITIVE_REPLAY_DRIFT')

cases = []

def add(name: str, bundle: dict, replay, note: str) -> None:
    summary = finalize(name, bundle, replay, note)
    expected = expected_by_name[name]
    raw = canonical_raw(bundle).encode('utf-8')
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected['mutated_full_candidate_canonical_sha256']:
        raise SystemExit(f'{name}:EXPECTED_SHA_DRIFT')
    if summary['internal_expected_rejection'] != expected['internal_expected_rejection']:
        raise SystemExit(f'{name}:EXPECTED_REASON_DRIFT')
    cases.append((name, bundle, raw, summary, expected))

b = deepcopy(base)
policy = b['request']['resolution_inputs']['policy']
policy['identity_threshold'] = '1.000000'
rehash_c(policy, 'policy_sha256', policy['contract'])
b['request']['resolution']['policy_sha256'] = policy['policy_sha256']
rehash_resolution(b['request']['resolution'])
b['request']['base_request']['policy_identity'] = 'g3-resolution-policy:' + policy['policy_sha256']
add('identity_threshold_policy_drift', b, actual_replay(b['request']),
    'Policy and all binding hashes are renewed, but the carried resolution still claims automatic decisions under the old threshold.')

b = deepcopy(base)
policy = b['request']['resolution_inputs']['policy']
policy['rules'][0]['purposes'].remove('classification')
rehash_c(policy, 'policy_sha256', policy['contract'])
b['request']['resolution']['policy_sha256'] = policy['policy_sha256']
rehash_resolution(b['request']['resolution'])
b['request']['base_request']['policy_identity'] = 'g3-resolution-policy:' + policy['policy_sha256']
add('classification_trust_rule_removed', b, actual_replay(b['request']),
    'The exact trust policy is changed and rehashed; unchanged automatic resolution must not survive policy replay.')

b = deepcopy(base)
proposals = b['request']['resolution_inputs']['proposals']
proposal = next(x for x in proposals['proposals'] if x['material_id'] == 'fixture-critical-1828')
entity = proposal['entities'][0]
old_label = entity['primary_label']
entity['primary_label'] = 'unsupported_insurance'
for label in entity['labels']:
    if label['taxonomy_label'] == old_label:
        label['taxonomy_label'] = 'unsupported_insurance'
rehash_c(proposal, 'proposal_sha256', 'material-proposal.830.g3.v1')
rehash_c(proposals, 'proposals_sha256', proposals['contract'])
b['request']['resolution']['proposals_sha256'] = proposals['proposals_sha256']
rehash_resolution(b['request']['resolution'])
add('selected_proposal_unsupported_classification', b, actual_replay(b['request']),
    'The selected proposal remains structurally valid and fully rehashed, but its label has no Catalog pack.')

b = deepcopy(base)
row = next(x for x in b['request']['resolution']['decisions'] if x['material_id'] == 'fixture-critical-1828')
row['disposition'] = 'MULTI'
row['queue_id'] = 'queue-g3'
row['queue_owner'] = 'product-owner-g3'
row['reason_codes'] = sorted(set(row['reason_codes']) | {'MULTI_ENTITY_REVIEW'})
rehash_c(row, 'decision_sha256', 'material-decision.830.g3.v1')
rehash_resolution(b['request']['resolution'])
add('single_child_false_multi_parent', b, None,
    'No extra fake child is introduced; the one-child frozen material cannot satisfy MULTI identity-cluster qualification.')

os.mkdir(DEST, 0o700)
manifest_cases = []
for ordinal, (name, bundle, raw, summary, expected) in enumerate(cases, 1):
    filename = f'{ordinal:02d}-{name.replace("_", "-")}.json'
    path = DEST / filename
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(raw)
    manifest_cases.append({
        'name': name,
        'path': str(path),
        'file_sha256': hashlib.sha256(raw).hexdigest(),
        'bytes': len(raw),
        'candidate_hash': bundle['candidate_hash'],
        'request_sha256': bundle['request']['request_sha256'],
        'resolution_batch_sha256': bundle['request']['resolution']['batch_sha256'],
        'internal_expected_rejection': summary['internal_expected_rejection'],
        'public_expected_rejection': summary['public_expected_rejection'],
        'actual_c_replay_batch_sha256': summary.get('actual_c_replay_batch_sha256'),
        'all_relevant_hash_checks_current': all(summary['hash_checks'].values()),
    })
manifest = {
    'contract': 'g3-go-c-semantics-materialized-cases.v1',
    'effect': 'PRIVATE_TMP_ONLY_NO_GO_RUNTIME',
    'oracle_script_ref': {'path': str(SOURCE), 'sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest()},
    'oracle_report_ref': {'path': str(REPORT), 'sha256': hashlib.sha256(REPORT.read_bytes()).hexdigest()},
    'positive_control_ref': {
        'path': str(FIXTURE),
        'file_sha256': hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        'candidate_hash': control.candidate_hash,
        'request_sha256': control.request.request_sha256,
        'resolution_batch_sha256': control.request.resolution.batch_sha256,
        'copied': False,
    },
    'cases': manifest_cases,
}
manifest_raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
manifest_path = DEST / 'manifest.json'
fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'wb') as handle:
    handle.write(manifest_raw)
print(json.dumps({'manifest': str(manifest_path), 'manifest_sha256': hashlib.sha256(manifest_raw).hexdigest(), 'cases': [{'name': x['name'], 'sha256': x['file_sha256']} for x in manifest_cases]}, ensure_ascii=False, indent=2))
