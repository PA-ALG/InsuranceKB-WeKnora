#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as d
from insurance_harness.knowledge_compiler import batch_entity_resolution_830_g3 as c
from insurance_harness.knowledge_compiler import concept_free_wiki_830_g2 as g2

ROOT = Path('/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation')
FIXTURE = ROOT / 'harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json'
OUT = Path('/private/tmp/g3-go-c-semantics-oracle-01.json')


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def without(obj: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in obj.items() if k != key}


def rehash_c(obj: dict[str, Any], field: str, domain: str) -> None:
    obj[field] = c._batch_sha256(domain, without(obj, field))


def rehash_d(obj: dict[str, Any], field: str, domain: str) -> None:
    obj[field] = d._batch_sha256(domain, without(obj, field))


def compile_output_hash(output: dict[str, Any]) -> str:
    return g2.digest('compile-output', output)


def base_request_hash(base: dict[str, Any]) -> str:
    return g2.digest('compile-request', base)


def canonical_raw(value: dict[str, Any]) -> str:
    return d._canonical_json(value)


def rehash_resolution(resolution: dict[str, Any]) -> None:
    counts = Counter(row['disposition'] for row in resolution['decisions'])
    resolution['disposition_counts'] = {
        name: counts[name] for name in ('MATCH', 'CREATE', 'MULTI', 'NEEDS_CONFIRM', 'QUARANTINE')
    }
    rehash_c(resolution, 'batch_sha256', resolution['contract'])


def rehash_request(request: dict[str, Any]) -> None:
    inputs = request['resolution_inputs']
    rehash_d(inputs, 'inputs_sha256', inputs['contract'])
    rehash_d(request, 'request_sha256', request['contract'])


def rehash_full_candidate(bundle: dict[str, Any]) -> None:
    request = bundle['request']
    rehash_request(request)
    base_hash = base_request_hash(request['base_request'])

    model = bundle['model_compile_result']
    model['output']['request_hash'] = base_hash
    model['execution']['raw_output'] = canonical_raw(model['output'])
    model['execution']['raw_output_hash'] = hashlib.sha256(
        model['execution']['raw_output'].encode('utf-8')
    ).hexdigest()
    model_context = {
        'request': request,
        'request_sha256': request['request_sha256'],
        'base_request_hash': base_hash,
        'output_mode': 'NEW_MEMBERS_ONLY',
    }
    model['execution']['context_hash'] = d._batch_sha256(
        'batch-concept-compile-context.830.g3.v1', model_context
    )

    final = bundle['compile_result']
    final['output']['request_hash'] = base_hash
    final['execution']['raw_output'] = canonical_raw(final['output'])
    final['execution']['raw_output_hash'] = hashlib.sha256(
        final['execution']['raw_output'].encode('utf-8')
    ).hexdigest()
    carry_context = {
        'request_sha256': request['request_sha256'],
        'model_compile_output_hash': compile_output_hash(model['output']),
        'model_compile_execution_sha256': d._batch_sha256(
            'batch-concept-model-execution.830.g3.v1', model['execution']
        ),
    }
    final['execution']['context_hash'] = d._batch_sha256(
        'batch-concept-carry-context.830.g3.v1', carry_context
    )

    review = bundle['review_result']
    review['output']['request_hash'] = base_hash
    review['output']['output_hash'] = compile_output_hash(final['output'])
    review['execution']['raw_output'] = canonical_raw(review['output'])
    review['execution']['raw_output_hash'] = hashlib.sha256(
        review['execution']['raw_output'].encode('utf-8')
    ).hexdigest()
    review_context = {
        'request': request,
        'candidate': final['output'],
        'request_sha256': request['request_sha256'],
        'base_request_hash': base_hash,
        'output_hash': review['output']['output_hash'],
    }
    review['execution']['context_hash'] = d._batch_sha256(
        'batch-concept-review-context.830.g3.v1', review_context
    )
    rehash_d(bundle, 'candidate_hash', bundle['contract'])


def typed_inputs(request: dict[str, Any]) -> tuple[Any, Any, Any, Any, Any]:
    inputs = request['resolution_inputs']
    return (
        control.request.catalog,
        c.BatchCorpusV1.model_validate(inputs['corpus']),
        c.ProposalBatchV1.model_validate(inputs['proposals']),
        c.ExistingEntitySnapshotV1.model_validate(inputs['existing_entities']),
        c.BatchResolutionPolicyV1.model_validate(inputs['policy']),
    )


def actual_replay(request: dict[str, Any]) -> Any:
    catalog, corpus, proposals, existing, policy = typed_inputs(request)
    return c.resolve_batch(
        catalog=catalog, corpus=corpus, proposals=proposals,
        existing_entities=existing, policy=policy,
    )


def disposition_summary(resolution: Any) -> list[dict[str, Any]]:
    return [
        {
            'material_id': row.material_id,
            'disposition': row.disposition,
            'reason_codes': list(row.reason_codes),
            'children': [
                {
                    'proposal_ref': child.proposal_ref,
                    'disposition': child.disposition,
                    'reason_codes': list(child.reason_codes),
                }
                for child in row.children
            ],
        }
        for row in resolution.decisions
    ]


def internal_reason(bundle: dict[str, Any]) -> str:
    try:
        d.BatchConceptCompileRequest830G3V1.model_validate(bundle['request'])
    except ValidationError as exc:
        text = str(exc)
        known = (
            'RESOLUTION_REPLAY_MISMATCH',
            'RESOLUTION_INPUT_BINDING_MISMATCH',
            'material decision collections are not canonical',
            'compiled batch closure or hash mismatch',
        )
        for item in known:
            if item in text:
                return item
        return 'UNEXPECTED_VALIDATION_ERROR:' + text[:240]
    except d.BatchConceptCompileError as exc:
        return str(exc)
    return 'ACCEPTED_UNEXPECTEDLY'



def public_reason(bundle: dict[str, Any]) -> str:
    raw = canonical_raw(bundle).encode('utf-8')
    try:
        d.validate_batch_candidate(raw)
    except d.BatchConceptCompileError as exc:
        return str(exc)
    return 'ACCEPTED_UNEXPECTEDLY'


def hash_checks(bundle: dict[str, Any]) -> dict[str, bool]:
    req = bundle['request']; inp = req['resolution_inputs']; res = req['resolution']
    model = bundle['model_compile_result']; final = bundle['compile_result']; review = bundle['review_result']
    base_hash = base_request_hash(req['base_request'])
    carry_context = {
        'request_sha256': req['request_sha256'],
        'model_compile_output_hash': compile_output_hash(model['output']),
        'model_compile_execution_sha256': d._batch_sha256(
            'batch-concept-model-execution.830.g3.v1', model['execution']
        ),
    }
    review_context = {
        'request': req,
        'candidate': final['output'],
        'request_sha256': req['request_sha256'],
        'base_request_hash': base_hash,
        'output_hash': compile_output_hash(final['output']),
    }
    return {
        'inputs_sha256_current': inp['inputs_sha256'] == d._batch_sha256(inp['contract'], without(inp, 'inputs_sha256')),
        'resolution_batch_sha256_current': res['batch_sha256'] == c._batch_sha256(res['contract'], without(res, 'batch_sha256')),
        'request_sha256_current': req['request_sha256'] == d._batch_sha256(req['contract'], without(req, 'request_sha256')),
        'model_context_hash_current': bundle['model_compile_result']['execution']['context_hash'] == d._batch_sha256(
            'batch-concept-compile-context.830.g3.v1', {
                'request': req,
                'request_sha256': req['request_sha256'],
                'base_request_hash': base_request_hash(req['base_request']),
                'output_mode': 'NEW_MEMBERS_ONLY',
            }),
        'model_raw_hash_current': model['execution']['raw_output_hash'] == hashlib.sha256(model['execution']['raw_output'].encode()).hexdigest(),
        'carry_context_hash_current': final['execution']['context_hash'] == d._batch_sha256(
            'batch-concept-carry-context.830.g3.v1', carry_context
        ),
        'final_raw_hash_current': final['execution']['raw_output_hash'] == hashlib.sha256(final['execution']['raw_output'].encode()).hexdigest(),
        'review_context_hash_current': review['execution']['context_hash'] == d._batch_sha256(
            'batch-concept-review-context.830.g3.v1', review_context
        ),
        'review_raw_hash_current': review['execution']['raw_output_hash'] == hashlib.sha256(review['execution']['raw_output'].encode()).hexdigest(),
        'candidate_hash_current': bundle['candidate_hash'] == d._batch_sha256(bundle['contract'], without(bundle, 'candidate_hash')),
    }


def finalize(name: str, bundle: dict[str, Any], expected_replay: Any | None, note: str) -> dict[str, Any]:
    rehash_full_candidate(bundle)
    raw = canonical_raw(bundle).encode('utf-8')
    result = {
        'name': name,
        'note': note,
        'mutated_full_candidate_canonical_sha256': hashlib.sha256(raw).hexdigest(),
        'attacked_request_sha256': bundle['request']['request_sha256'],
        'attacked_resolution_batch_sha256': bundle['request']['resolution']['batch_sha256'],
        'mutated_input_hashes': {
            'corpus_sha256': bundle['request']['resolution_inputs']['corpus']['corpus_sha256'],
            'proposals_sha256': bundle['request']['resolution_inputs']['proposals']['proposals_sha256'],
            'existing_snapshot_sha256': bundle['request']['resolution_inputs']['existing_entities']['snapshot_sha256'],
            'policy_sha256': bundle['request']['resolution_inputs']['policy']['policy_sha256'],
            'inputs_sha256': bundle['request']['resolution_inputs']['inputs_sha256'],
        },
        'hash_checks': hash_checks(bundle),
        'internal_expected_rejection': internal_reason(bundle),
        'public_expected_rejection': public_reason(bundle),
    }
    if expected_replay is not None:
        result['actual_c_replay_batch_sha256'] = expected_replay.batch_sha256
        result['actual_c_replay'] = disposition_summary(expected_replay)
        result['attacked_resolution_equals_actual_replay'] = (
            bundle['request']['resolution'] == expected_replay.model_dump(mode='json')
        )
    return result


base = json.loads(FIXTURE.read_bytes())
control = d.validate_batch_candidate(FIXTURE.read_bytes())
print('positive-control-pass', flush=True)
control_replay = c.resolve_batch(
    catalog=control.request.catalog,
    corpus=control.request.resolution_inputs.corpus,
    proposals=control.request.resolution_inputs.proposals,
    existing_entities=control.request.resolution_inputs.existing_entities,
    policy=control.request.resolution_inputs.policy,
)
assert control_replay == control.request.resolution
vectors: list[dict[str, Any]] = []

# 1. Raise the frozen identity threshold above every 0.99 proposal.
b = deepcopy(base)
policy = b['request']['resolution_inputs']['policy']
policy['identity_threshold'] = '1.000000'
rehash_c(policy, 'policy_sha256', policy['contract'])
b['request']['resolution']['policy_sha256'] = policy['policy_sha256']
rehash_resolution(b['request']['resolution'])
b['request']['base_request']['policy_identity'] = 'g3-resolution-policy:' + policy['policy_sha256']
replay = actual_replay(b['request'])
vectors.append(finalize(
    'identity_threshold_policy_drift', b, replay,
    'Policy and all binding hashes are renewed, but the carried resolution still claims automatic decisions under the old threshold.',
))
print('identity-threshold-vector-pass', flush=True)

# 2. Remove classification trust from the sole exact trust rule.
b = deepcopy(base)
policy = b['request']['resolution_inputs']['policy']
policy['rules'][0]['purposes'].remove('classification')
rehash_c(policy, 'policy_sha256', policy['contract'])
b['request']['resolution']['policy_sha256'] = policy['policy_sha256']
rehash_resolution(b['request']['resolution'])
b['request']['base_request']['policy_identity'] = 'g3-resolution-policy:' + policy['policy_sha256']
replay = actual_replay(b['request'])
vectors.append(finalize(
    'classification_trust_rule_removed', b, replay,
    'The exact trust policy is changed and rehashed; unchanged automatic resolution must not survive policy replay.',
))
print('trust-rule-vector-pass', flush=True)

# 3. Replace one selected proposal's classification with an unsupported catalog label.
b = deepcopy(base)
proposals = b['request']['resolution_inputs']['proposals']
proposal = next(x for x in proposals['proposals'] if x['material_id'] == 'fixture-critical-1828')
entity = proposal['entities'][0]
old_label = entity['primary_label']; entity['primary_label'] = 'unsupported_insurance'
for label in entity['labels']:
    if label['taxonomy_label'] == old_label:
        label['taxonomy_label'] = 'unsupported_insurance'
rehash_c(proposal, 'proposal_sha256', 'material-proposal.830.g3.v1')
rehash_c(proposals, 'proposals_sha256', proposals['contract'])
b['request']['resolution']['proposals_sha256'] = proposals['proposals_sha256']
rehash_resolution(b['request']['resolution'])
replay = actual_replay(b['request'])
vectors.append(finalize(
    'selected_proposal_unsupported_classification', b, replay,
    'The selected proposal remains structurally valid and fully rehashed, but its label has no Catalog pack.',
))
print('unsupported-classification-vector-pass', flush=True)

# 4. Claim MULTI for a material with only one child/identity cluster.
b = deepcopy(base)
row = next(x for x in b['request']['resolution']['decisions'] if x['material_id'] == 'fixture-critical-1828')
row['disposition'] = 'MULTI'; row['queue_id'] = 'queue-g3'; row['queue_owner'] = 'product-owner-g3'
row['reason_codes'] = sorted(set(row['reason_codes']) | {'MULTI_ENTITY_REVIEW'})
rehash_c(row, 'decision_sha256', 'material-decision.830.g3.v1')
rehash_resolution(b['request']['resolution'])
vectors.append(finalize(
    'single_child_false_multi_parent', b, None,
    'No extra fake child is introduced; the one-child frozen material cannot satisfy MULTI identity-cluster qualification.',
))
print('false-multi-vector-pass', flush=True)

assert all(all(row['hash_checks'].values()) for row in vectors)
assert all(row['public_expected_rejection'] == 'BATCH_CANDIDATE_INVALID' for row in vectors)
assert all(row['internal_expected_rejection'] != 'ACCEPTED_UNEXPECTEDLY' for row in vectors)
assert all(row.get('attacked_resolution_equals_actual_replay') is False for row in vectors if 'attacked_resolution_equals_actual_replay' in row)

result = {
    'contract': 'g3-go-c-semantics-independent-oracle.v1',
    'effect': 'READ_ONLY_FROZEN_FIXTURE_AND_PYTHON_ONLY',
    'purpose': 'future frozen Go mirror review; not labels, Golden, model output, or implementation authority',
    'frozen_inputs': {
        'commit': 'e85fa570dc7b3d86c77a7fcc8682523f67b9db0d',
        'c_source_sha256': file_sha(ROOT / 'harness/src/insurance_harness/knowledge_compiler/batch_entity_resolution_830_g3.py'),
        'd_source_sha256': file_sha(ROOT / 'harness/src/insurance_harness/knowledge_compiler/batch_concept_compile_830_g3.py'),
        'candidate_fixture_sha256': file_sha(FIXTURE),
        'candidate_hash': control.candidate_hash,
        'request_sha256': control.request.request_sha256,
        'resolution_batch_sha256': control.request.resolution.batch_sha256,
    },
    'positive_control': {
        'validate_batch_candidate': 'PASS',
        'resolution_replay_equal': True,
        'actual_c_replay_batch_sha256': control_replay.batch_sha256,
        'dispositions': disposition_summary(control_replay),
    },
    'coverage_note': 'The frozen 342 fixture contains exactly five materials and all five are selected. A non-selected-material vector and a true multi-child positive were not fabricated.',
    'vectors': vectors,
}
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({
    'output': str(OUT), 'sha256': file_sha(OUT), 'vectors': [
        (x['name'], x['internal_expected_rejection'], x['public_expected_rejection']) for x in vectors
    ]
}, ensure_ascii=False, indent=2))
