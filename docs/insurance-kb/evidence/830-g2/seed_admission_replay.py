"""Frozen seed admission replay only; no compiler, reviewer, provider or runtime."""
import hashlib
import json
import subprocess
from pathlib import Path
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import ValueScore
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import admission_disposition

ROOT = Path('/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g2-concept-free-wiki')
SEEDS = ROOT / 'docs/insurance-kb/evidence/830-g2/seed-cases.json'
PROJECTION = ROOT / 'docs/insurance-kb/evidence/830-g2/inputs/terms-native-projection.json'
INVENTORY = Path('/private/tmp/g2-seed-replay-inventory.json')
SCORE_KEYS = ('business_value','reuse','evidence_quality','definability','novel_identity','name_stability')

def sha(b): return hashlib.sha256(b).hexdigest()
def canonical(o): return json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def require(ok, why):
    if not ok: raise ValueError(why)


SOURCE_HEAD = 'd7c67303916e6f608458de4980cf83d807390022'
MODULE_HASHES = {'concept_compile_830_g2.py': '025420e7c047ef3d7ced42d2f2f3a18105a2e42058e50d01f8ff9f6d6f8a9d94', 'concept_free_wiki_830_g2.py': '9065688ccf9c0f37590ff6d580daabc4fd113a73ed41880b37ac5684b95cd1dc'}
def source_guard():
    require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==SOURCE_HEAD,'source HEAD drift')
    for name,digest in MODULE_HASHES.items():
        require(sha((ROOT/'harness/src/insurance_harness/knowledge_compiler'/name).read_bytes())==digest,'protocol source drift: '+name)

def derive(item, inventory):
    # Only input signals and independently frozen replay setup; no expected result.
    if item.get('synthetic_mutation') in ('advertising_noise','ocr_noise'):
        return 'reject', 'frozen synthetic noise signal; semantic classifier NOT_RUN'
    if item.get('independent_review_expected') == 'REJECT':
        return 'reject', 'frozen upstream reject signal; actual independent reviewer NOT_RUN'
    if item.get('link_target_scope', item['scope']) != item['scope']:
        return 'reject', 'link target is outside input scope'
    if item.get('link_only'):
        require(inventory['scope'] == item['scope'], 'inventory scope mismatch')
        if item['canonical_target'] not in inventory['canonical_targets']:
            return 'reject', 'target absent in frozen synthetic inventory; live DB NOT_RUN'
    sources = item.get('source_evidence', [])
    if sources and item.get('existing_evidence') == sources and item.get('existing_content') == ''.join(e['quote'] for e in sources):
        return 'duplicate', 'incoming content and evidence exactly equal existing input'
    if item.get('same_identity_confirmed') and item.get('alias'):
        return 'alias_link', 'frozen same-identity and alias input'
    if item.get('field_key'): return 'field_rule', 'input declares a schema field'
    if item.get('existing_identity') == 'same': return 'update', 'same existing identity input'
    if item.get('existing_identity') == 'different_sense' and item.get('sense_key') != item.get('existing_sense'):
        return 'sense', 'different existing sense input'
    require(item.get('placement') in (None, 'concept_definition'), 'unsupported placement')
    return 'new_page', 'default concept admission candidate'

def check_evidence(e, projection):
    checks = {
        'document': e['source_type'] == 'DOCUMENT',
        'revision': e['source_revision_id'] == projection['source_revision_id'],
        'file': e['source_content_hash'] == projection['original_file_sha256'],
        'manifest': e['parse_manifest_hash'] == projection['parse_manifest_sha256'],
        'parser': e['parser_identity'] == projection['adapter_version'],
    }
    loc = e['locator']
    checks['locator'] = loc['kind'] == 'PDF_PAGE_BBOX' and loc['offset_unit'] == 'UNICODE_CODE_POINT'
    page = next(p for p in projection['pages'] if p['page_number'] == loc['page_number'])
    text = page['canonical_page_text']
    start,end = loc['char_start'],loc['char_end']
    checks['page_hash'] = sha(text.encode()) == page['page_text_sha256']
    checks['quote'] = 0 <= start < end <= len(text) and text[start:end] == e['quote']
    checks['quote_hash'] = sha(e['quote'].encode()) == e['quote_sha256']
    spans = [next(s for s in page['spans'] if s['span_id'] == sid) for sid in loc['span_ids']]
    checks['span_unique'] = bool(spans) and len(set(loc['span_ids'])) == len(spans)
    checks['span_ranges'] = all(any(s['char_start'] <= cp < s['char_end'] for s in spans) for cp in range(start,end)) and all(s['char_start'] < end and s['char_end'] > start for s in spans)
    checks['span_text'] = all(s['page_number'] == loc['page_number'] and text[s['char_start']:s['char_end']] == s['exact_text'] and sha(s['exact_text'].encode()) == s['text_sha256'] for s in spans)
    checks['rectangles'] = [r for s in spans for r in s['rects']] == loc['rects']
    require(all(checks.values()), 'source evidence failed: '+str(checks))
    return {'status':'PASS','quote_sha256':e['quote_sha256'],'checks':checks}

def main():
    source_guard()
    raw = SEEDS.read_bytes(); native = PROJECTION.read_bytes(); invraw=INVENTORY.read_bytes()
    require(sha(raw)=='7725bc78806e6889fff56543819bb790435eaf122844573caf103aae86090a2b','seed drift')
    require(sha(native)=='f4fd8a439ffb1ef5a2c01c4363f8f9692748d10254c611cba1f0112d2dc7de6b','projection drift')
    seeds=json.loads(raw); projection=json.loads(native); inventory=json.loads(invraw)
    require(inventory['classification']=='SYNTHETIC_PROTOCOL_SETUP_NOT_ACTIVE_INVENTORY','inventory classification')
    require(inventory['seed_sha256']==sha(raw),'inventory seed binding')
    require(seeds['denominator']==len(seeds['cases'])==24,'denominator drift')
    rows=[]
    for case in seeds['cases']:
        require(sha(canonical({k:v for k,v in case.items() if k!='digest'}))==case['digest'],'case digest')
        item=case['input']; proofs=[check_evidence(e,projection) for e in item.get('source_evidence',[])]
        placement,reason=derive(item,inventory)
        args=dict(evidence_valid=bool(proofs),identity_valid=not item.get('identity_missing',False),required=item.get('required',False),attempted=item.get('attempted',True),value_state=item.get('value_state','present'))
        components=item.get('score_components')
        if components is not None:
            score=ValueScore(**dict(zip(SCORE_KEYS,components,strict=True))).total
            actual=admission_disposition(placement,score,**args)
            score_receipt={'status':'PASS','total':score}
        else:
            endpoints=[admission_disposition(placement,s,**args) for s in (0,100)]
            require(endpoints[0]==endpoints[1],'missing score affects outcome')
            actual=endpoints[0]; score_receipt={'status':'NOT_REQUIRED_FOR_THIS_BRANCH','boundary_scores':[0,100],'boundary_outputs':endpoints}
        expected=case['expected']['disposition'] # consulted only after actual result
        rows.append({'case_id':case['case_id'],'seed_digest':case['digest'],'native_evidence':proofs,'value_score':score_receipt,'pre_admission':{'placement':placement,'basis':reason,**args},'admission_actual':actual,'expected':expected,'comparison':'PASS' if actual==expected else 'FAIL','full_compile_review_active':'NOT_RUN'})
    require(SEEDS.read_bytes()==raw and PROJECTION.read_bytes()==native and INVENTORY.read_bytes()==invraw,'input changed')
    source_guard()
    result={'source_head':SOURCE_HEAD,'protocol_module_sha256':MODULE_HASHES,'contract':'830-g2-seed-admission-replay.v1','classification':'PROTOCOL_REPLAY_NOT_GOLDEN','status':'PASS' if all(r['comparison']=='PASS' for r in rows) else 'FAIL','seed_sha256':sha(raw),'projection_sha256':sha(native),'inventory_sha256':sha(invraw),'runner_sha256':sha(Path(__file__).read_bytes()),'denominator':24,'admission_pass':sum(r['comparison']=='PASS' for r in rows),'native_evidence_checks':sum(len(r['native_evidence']) for r in rows),'score_shape_checks':sum(r['value_score']['status']=='PASS' for r in rows),'provider_calls':0,'database_reads':0,'database_writes':0,'active_snapshots_created':0,'full_compile_request_validation':'NOT_RUN','independent_reviewer':'NOT_RUN','semantic_quality':'Q0_DEFERRED','cases':rows}
    output=Path('/private/tmp/g2-seed-admission-replay-source-bound.json')
    result_bytes=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode()
    require(not output.exists() or output.read_bytes()==result_bytes,'refuse to overwrite different execution receipt')
    output.write_bytes(result_bytes)
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},ensure_ascii=False))
if __name__=='__main__': main()
