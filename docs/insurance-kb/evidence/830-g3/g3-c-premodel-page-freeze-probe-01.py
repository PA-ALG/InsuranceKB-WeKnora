#!/usr/bin/env python3
import gzip, hashlib, json, re
from pathlib import Path

ROOT=Path('/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation')
OUT=Path('/private/tmp/g3-c-premodel-page-freeze-probe-01.json')

def sha(s): return hashlib.sha256(s.encode('utf-8')).hexdigest()
def load_native(rel):
    with gzip.open(ROOT/rel,'rt',encoding='utf-8') as f: wrap=json.load(f)
    meta=wrap.get('metadata')
    if meta is None: meta=json.loads(wrap['raw_metadata'])
    san=meta['sanitized_json']; md=wrap['markdown']
    checks={
      'markdown_sha_matches':sha(md)==san['markdown_sha256'],
      'page_slices_hash_match':True,
      'visible_codepoints_boxed_once':True,
    }
    pages=[]
    for p in san['pages']:
      a,b=p['global_codepoint_start'],p['global_codepoint_end']; pt=md[a:b]
      checks['page_slices_hash_match'] &= sha(pt)==p['page_text_sha256']
      counts={}
      for box in p['bboxes']:
        for i in range(box['global_codepoint_start'],box['global_codepoint_end']): counts[i]=counts.get(i,0)+1
      checks['visible_codepoints_boxed_once'] &= all(ch.isspace() or counts.get(i,0)==1 for i,ch in enumerate(md[a:b],a))
      pages.append((p,pt,counts))
    return wrap,san,pages,checks

def exact_occurrences(text, needle):
    out=[]; start=0
    while True:
      i=text.find(needle,start)
      if i<0:return out
      out.append(i); start=i+1

def line_candidates(block_text,pages,min_visible=8):
    candidates=[]
    for m in re.finditer(r'[^\r\n]+',block_text):
      raw=m.group(); l=len(raw)-len(raw.lstrip()); r=len(raw.rstrip())
      q=raw.strip(); start=m.start()+l; end=m.start()+r
      if len(''.join(c for c in q if not c.isspace()))<min_visible: continue
      hits=[]
      for p,pt,counts in pages:
        for pos in exact_occurrences(pt,q):
          gs=p['global_codepoint_start']+pos
          boxed=all(ch.isspace() or counts.get(gs+j)==1 for j,ch in enumerate(q))
          if boxed: hits.append((p,pt,pos,gs))
      if len(hits)==1:
        p,pt,pos,gs=hits[0]
        vis=[p['bboxes'][0]['bbox']] if False else []
        # Aggregate exact visible-codepoint boxes from page metadata.
        boxes=[]
        for box in p['bboxes']:
          if box['global_codepoint_end']<=gs or box['global_codepoint_start']>=gs+len(q):continue
          for j in range(max(gs,box['global_codepoint_start']),min(gs+len(q),box['global_codepoint_end'])):
            if not block_text[start+(j-gs)].isspace(): boxes.append(box['bbox'])
        bbox=None
        if boxes:bbox=[min(x[0] for x in boxes),min(x[1] for x in boxes),max(x[2] for x in boxes),max(x[3] for x in boxes)]
        candidates.append({'block_start':start,'block_end':end,'quote_sha256':sha(q),'quote_codepoints':len(q),'visible_codepoints':sum(not c.isspace() for c in q),'page_number':p['page_number'],'page_text_sha256':p['page_text_sha256'],'page_global_start':gs,'page_global_end':gs+len(q),'bbox':bbox,'global_occurrence_count':1})
    return sorted(candidates,key=lambda x:(-x['visible_codepoints'],x['block_start'],x['page_number']))

def prediction_summary(material, markdown, pages, doc):
    md=markdown
    rows=[]
    for c in doc['chunks']:
      text=md[c['start']:c['end']]
      assert sha(text)==c['content_sha256']
      overlaps=[p['page_number'] for p,pt,_ in pages if max(c['start'],p['global_codepoint_start'])<min(c['end'],p['global_codepoint_end']) and md[max(c['start'],p['global_codepoint_start']):min(c['end'],p['global_codepoint_end'])].strip()]
      cand=line_candidates(text,pages)
      rows.append({'seq':c['seq'],'start':c['start'],'end':c['end'],'content_sha256':c['content_sha256'],'overlapping_pages':overlaps,'mechanical_candidate':cand[0] if cand else None})
    cross=[x for x in rows if len(x['overlapping_pages'])>1]
    sample_seqs=sorted(set([0]+([cross[0]['seq']] if cross else [])+([rows[-1]['seq']] if material=='g3-material-21' else [])))
    return {'authority':'PREDICTION_FEASIBILITY_ONLY_NOT_W1_SOURCE','predicted_chunk_count':len(rows),'cross_page_predicted_chunks':len(cross),'sample_rows':[x for x in rows if x['seq'] in sample_seqs],'all_chunks_have_candidate':all(x['mechanical_candidate'] for x in rows),'candidate_pages_across_all_predictions':sorted(set(x['mechanical_candidate']['page_number'] for x in rows if x['mechanical_candidate']))}

inv=json.load(open(ROOT/'docs/insurance-kb/evidence/830-g3/native-capture-inventory-v2.json'))
invmap={x['material_id']:x for x in inv['documents']}
loaded={}
for mid in ('g3-material-01','g3-material-17','g3-material-21'):
 loaded[mid]=load_native(invmap[mid]['path'])

cust=json.load(open(ROOT/'docs/insurance-kb/evidence/830-g2/inputs/g1-custody-chunks.json'))['chunks']
old=[]
for c in sorted(cust,key=lambda x:x['chunk_index']):
 text=c.get('content',c.get('text'))
 cand=line_candidates(text,loaded['g3-material-01'][2])
 old.append({'block_id':c['id'],'knowledge_id':c['knowledge_id'],'parse_attempt':c['parse_attempt'],'chunk_index':c['chunk_index'],'text_sha256':sha(text),'text_codepoints':len(text),'mechanical_candidate':cand[0] if cand else None,'candidate_count':len(cand)})

wl=json.load(open('/private/tmp/g3-embedding-prepared-v1/embedding-whitelist.json'))
docs={x['material_id']:x for x in wl['documents']}
preds={mid:prediction_summary(mid,loaded[mid][0]['markdown'],loaded[mid][2],docs[mid]) for mid in ('g3-material-17','g3-material-21')}

result={
 'contract':'g3-c-premodel-page-freeze-bounded-probe.v1',
 'effect':'READ_ONLY_LOCAL_BYTES_ONLY',
 'no_business_evidence_or_labels_created':True,
 'inputs':{
   'native_capture_inventory_sha256':hashlib.sha256((ROOT/'docs/insurance-kb/evidence/830-g3/native-capture-inventory-v2.json').read_bytes()).hexdigest(),
   'old_w1_chunks_sha256':hashlib.sha256((ROOT/'docs/insurance-kb/evidence/830-g2/inputs/g1-custody-chunks.json').read_bytes()).hexdigest(),
   'offline_embedding_whitelist_sha256':hashlib.sha256(Path('/private/tmp/g3-embedding-prepared-v1/embedding-whitelist.json').read_bytes()).hexdigest(),
 },
 'native_integrity':{mid:{'capture_file_sha256':invmap[mid]['capture_file_sha256'],'native_sha256':invmap[mid]['native_sha256'],'markdown_sha256':invmap[mid]['markdown_sha256'],'pages':invmap[mid]['pages'],'checks':loaded[mid][3]} for mid in loaded},
 'old_01_actual_w1':{'authority':'ACTUAL_SAVED_W1_ROWS','blocks':old,'all_blocks_have_candidate':all(x['mechanical_candidate'] for x in old)},
 'offline_samples':preds,
 'material_21_capacity':{'native_substantive_page_count':5,'predicted_block_count':docs['g3-material-21']['chunk_count'],'maximum_assignable_pages_without_duplicate_block_key':docs['g3-material-21']['chunk_count'],'full_five_page_coverage_supported':False,'status':'BACKLOG_UNCHANGED_PENDING_ACTUAL_W1_READBACK'},
}
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'output':str(OUT),'sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'old01_all':result['old_01_actual_w1']['all_blocks_have_candidate'],'m17_all_prediction_candidates':preds['g3-material-17']['all_chunks_have_candidate'],'m21_all_prediction_candidates':preds['g3-material-21']['all_chunks_have_candidate'],'m17_samples':[(x['seq'],x['overlapping_pages'],x['mechanical_candidate']['page_number'] if x['mechanical_candidate'] else None) for x in preds['g3-material-17']['sample_rows']],'m21_samples':[(x['seq'],x['overlapping_pages'],x['mechanical_candidate']['page_number'] if x['mechanical_candidate'] else None) for x in preds['g3-material-21']['sample_rows']]},indent=2))
