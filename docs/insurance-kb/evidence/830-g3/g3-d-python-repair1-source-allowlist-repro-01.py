from __future__ import annotations
import importlib
from pathlib import Path

ROOT=Path('/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation')
FIX=ROOT/'harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json'
d=importlib.import_module('insurance_harness.knowledge_compiler.batch_concept_compile_830_g3')
c=importlib.import_module('insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3')
g2=importlib.import_module('insurance_harness.knowledge_compiler.concept_compile_830_g2')
bundle=d.validate_batch_candidate(FIX.read_bytes())
request=bundle.request
binding=next(x for x in request.entity_bindings if x.resolution_disposition=='CREATE')
material_id=binding.source_material_ids[0]
entry=next(x for x in request.resolution_inputs.corpus.entries if x.material_id==material_id)
identity_block=entry.blocks[0]
extra=identity_block.model_copy(update={'block_id':identity_block.block_id+'-field-only','text':identity_block.text+'\nFIELD_ONLY_FACT'})
entry_payload=entry.model_dump(mode='json',exclude={'entry_sha256'})
entry_payload['blocks']=sorted([*entry.blocks,extra],key=lambda x:(x.revision_id,x.block_id))
entry_payload['entry_sha256']=c._batch_sha256('corpus-entry.830.g3.v1',{k:v for k,v in entry_payload.items() if k!='entry_sha256'})
expanded_entry=c.CorpusEntryV1.model_validate(entry_payload)
assert not c._entry_source_reasons(expanded_entry,request.resolution_inputs.corpus)

base_payload=request.base_request.model_dump(mode='json')
base_payload['sources']=sorted([*request.base_request.sources,extra],key=lambda x:(x.revision_id,x.block_id))
expanded_base=g2.CompileRequest.model_validate(base_payload)

source_keys={(x.revision_id,x.block_id) for x in expanded_base.sources}
existing=(*expanded_base.existing_definitions,*expanded_base.existing_fields,*expanded_base.existing_pages)
required={(e.revision_id,e.block_id) for member in existing for e in member.evidence}
required.update((e.evidence.revision_id,e.evidence.block_id) for b in request.entity_bindings for e in b.resolution_evidence)
extra_key=(extra.revision_id,extra.block_id)
owner_allowed={(x.revision_id,x.block_id) for x in expanded_entry.blocks}

print('material_id='+material_id)
print('expanded_corpus_entry_valid=true')
print('expanded_base_compile_request_valid=true')
identity_fields=('tenant_id','space_id','raw_kb_id','knowledge_id','parse_attempt','revision_id','source_hash','parse_hash','parser_identity')
same_identity=all(getattr(extra,k)==getattr(identity_block,k) for k in identity_fields)
print('extra_block_matches_same_registered_source_identity='+str(same_identity).lower())
print('extra_block_in_selected_material_owner_allowlist='+str(extra_key in owner_allowed).lower())
print('extra_block_in_request_source_keys='+str(extra_key in source_keys).lower())
print('extra_block_in_existing_or_resolution_evidence_keys='+str(extra_key in required).lower())
print('current_request_closure_source_keys_equal_required='+str(source_keys==required).lower())
print('difference='+repr(sorted(source_keys-required)))
assert extra_key in owner_allowed and extra_key in source_keys and extra_key not in required and source_keys!=required
print('REPRODUCED: source-layer-valid selected-material field block is rejected by current exact source-key closure')
