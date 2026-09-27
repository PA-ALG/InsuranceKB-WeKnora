import runpy, hashlib
from insurance_harness.knowledge_compiler import batch_entity_resolution_830_g3 as g
from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_sha256_830_g3
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import evidence_for
m=runpy.run_path('harness/tests/test_batch_entity_resolution_830_g3.py')
for body in ['首行\n第二行', '首行\r\n第二行', '首行\t第二行']:
    entry=m['_entry'](material_id='review',text=body)
    assert g.CorpusEntryV1.model_validate_json(entry.model_dump_json()) == entry
    assert entry.blocks[0].text == body
    ev=evidence_for(entry.blocks[0],0,len(body))
    pe=g.ProposalEvidenceV1(evidence_id='review-evidence',entity_proposal_ref=None,purpose='material_role',field_key=None,evidence=ev)
    g._validate_typed_batch_text(pe)
    assert g.ProposalEvidenceV1.model_validate_json(pe.model_dump_json()).evidence.quote == body
    typed=g._hashed(g.CorpusEntryV1,object_type='corpus-entry.830.g3.v1',hash_field='entry_sha256',payload=entry.model_dump(mode='python',exclude={'entry_sha256','blocks'})|{'blocks':entry.blocks})
    assert typed.entry_sha256 == entry.entry_sha256
    print('PASS exact body/quote and typed construction:',repr(body),entry.entry_sha256)
entry=m['_entry'](material_id='review',text='clean')
for control in ['\t','\n','\r','\0','\x7f']:
    bad=entry.model_dump(mode='json')
    bad['blocks'][0]['parser_identity']='parser'+control+'id'
    try:
        bad['entry_sha256']=batch_sha256_830_g3('corpus-entry.830.g3.v1',{k:v for k,v in bad.items() if k!='entry_sha256'})
        g.CorpusEntryV1.model_validate(bad)
    except (ValueError,TypeError): pass
    else: raise AssertionError('nested source identity accepted '+repr(control))
    print('PASS rehashed nested identity rejected:',repr(control))
print('ROOT INDEPENDENT PROBE PASS; provider/DB/network/container/upload effects=0')
