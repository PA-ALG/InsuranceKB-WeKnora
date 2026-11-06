-- Offline only: stop serving, then complete the Go restorer's protocol/history
-- verification and reconstruction. Cleared markers alone are not restoration proof.
-- One DO statement keeps validation, locks and DDL in the same transaction even
-- when a migration driver executes statements separately. Locks last until commit.
DO $down$
DECLARE
 owner RECORD;
 scope_row RECORD;
 root RECORD;
 chunk RECORD;
 object_row RECORD;
 old_member RECORD;
 old_json JSONB;
 block_index INTEGER;
 ref_index INTEGER;
 block_count BIGINT;
 member_index BIGINT;
 old_count BIGINT;
 previous_slug BYTEA;
 field_value TEXT;
 field_bytes BYTEA;
 content_bytes BYTEA;
 chunk_bytes BYTEA;
 root_bytes BYTEA;
 nul BYTEA := decode('00','hex');
BEGIN
 LOCK TABLE wiki_releases, wiki_release_preparations, wiki_release_members,
  enterprise_member_scopes, enterprise_member_contents, enterprise_member_chunks,
  enterprise_member_sets, enterprise_member_releases, enterprise_member_preparations,
  enterprise_member_progress, enterprise_member_validation_pending,
  enterprise_member_validation_failures IN ACCESS EXCLUSIVE MODE;

 IF EXISTS(SELECT 1 FROM wiki_releases WHERE member_storage <> '')
 OR EXISTS(SELECT 1 FROM wiki_release_preparations WHERE member_storage <> '')
 OR EXISTS(SELECT 1 FROM enterprise_member_scopes WHERE mode <> 'legacy')
 OR EXISTS(SELECT 1 FROM enterprise_member_validation_pending)
 THEN RAISE EXCEPTION 'member storage legacy restoration required'; END IF;

 -- A Release also owns its original preparation representation; absence of that
 -- mapping cannot be treated as proof that its array has been restored.
 IF EXISTS(
  SELECT 1 FROM enterprise_member_releases m
  JOIN wiki_releases r ON r.release_id=m.release_id
  LEFT JOIN enterprise_member_preparations p
   ON p.preparation_id=r.preparation_id AND p.scope_id=m.scope_id
  WHERE p.preparation_id IS NULL
 ) THEN RAISE EXCEPTION 'member storage preparation restoration missing'; END IF;

 -- Check both directions: a lost Release mapping must not hide its old member
 -- rows while the original preparation mapping survives.
 IF EXISTS(
  SELECT 1 FROM enterprise_member_preparations p
  JOIN wiki_releases r ON r.preparation_id=p.preparation_id
  LEFT JOIN enterprise_member_releases m
   ON m.release_id=r.release_id AND m.scope_id=p.scope_id
  WHERE m.release_id IS NULL
 ) OR EXISTS(
  SELECT 1 FROM enterprise_member_progress p
  LEFT JOIN enterprise_member_releases m ON m.release_id=p.release_id AND m.scope_id=p.scope_id
  WHERE p.phase IN ('verified','restored') AND m.release_id IS NULL
 ) THEN RAISE EXCEPTION 'member storage release restoration mapping missing'; END IF;

 CREATE TEMP TABLE st1_down_member_seen(slug BYTEA PRIMARY KEY) ON COMMIT DROP;
 FOR owner IN
  SELECT 'release' AS owner_type,m.release_id AS owner_id,m.scope_id,m.root_digest,m.verified,
   m.tenant_id,m.space_id,m.raw_kb_id,m.wiki_kb_id,
   r.tenant_id AS old_tenant_id,r.space_id AS old_space_id,
   r.raw_kb_id AS old_raw_kb_id,r.wiki_kb_id AS old_wiki_kb_id,NULL::JSONB AS old_members
  FROM enterprise_member_releases m LEFT JOIN wiki_releases r ON r.release_id=m.release_id
  UNION ALL
  SELECT 'preparation',m.preparation_id,m.scope_id,m.root_digest,m.verified,
   m.tenant_id,m.space_id,m.raw_kb_id,m.wiki_kb_id,
   p.tenant_id,p.space_id,p.raw_kb_id,p.wiki_kb_id,p.members
  FROM enterprise_member_preparations m
  LEFT JOIN wiki_release_preparations p ON p.preparation_id=m.preparation_id
 LOOP
  IF owner.verified IS DISTINCT FROM TRUE OR
   ROW(owner.tenant_id,owner.space_id,owner.raw_kb_id,owner.wiki_kb_id) IS DISTINCT FROM
   ROW(owner.old_tenant_id,owner.old_space_id,owner.old_raw_kb_id,owner.old_wiki_kb_id)
  THEN RAISE EXCEPTION 'member storage owner integrity failure'; END IF;
  SELECT * INTO scope_row FROM enterprise_member_scopes WHERE id=owner.scope_id;
  IF NOT FOUND OR
   ROW(owner.tenant_id,owner.space_id,owner.raw_kb_id,owner.wiki_kb_id) IS DISTINCT FROM
   ROW(scope_row.tenant_id,scope_row.space_id,scope_row.raw_kb_id,scope_row.wiki_kb_id)
  THEN RAISE EXCEPTION 'member storage scope integrity failure'; END IF;
  SELECT * INTO root FROM enterprise_member_sets
   WHERE scope_id=owner.scope_id AND digest=owner.root_digest;
  IF NOT FOUND THEN RAISE EXCEPTION 'member storage root missing'; END IF;
  IF root.codec <> 1 OR octet_length(root.digest) <> 32 OR root.member_count < 0 OR root.chunk_count < 0
   OR root.order_mode NOT IN ('slug_asc','legacy_sequence')
   OR octet_length(root.blocks)::BIGINT <> root.chunk_count::BIGINT*36
   OR (owner.owner_type='release' AND root.order_mode <> 'slug_asc')
  THEN RAISE EXCEPTION 'member storage root integrity failure'; END IF;
  field_bytes := convert_to(root.order_mode,'UTF8');
  root_bytes := convert_to('enterprise-member-chunk-set.v1','UTF8')||nul||
   int8send(octet_length(field_bytes)::BIGINT)||field_bytes||
   int8send(root.member_count)||int4send(root.chunk_count)||root.blocks;
  IF pg_catalog.sha256(root_bytes) IS DISTINCT FROM root.digest
  THEN RAISE EXCEPTION 'member storage root hash failure'; END IF;
  IF owner.owner_type='release' THEN
   SELECT count(*) INTO old_count FROM wiki_release_members WHERE release_id=owner.owner_id;
  ELSE
   IF jsonb_typeof(owner.old_members) <> 'array'
   THEN RAISE EXCEPTION 'member storage preparation array missing'; END IF;
   old_count := jsonb_array_length(owner.old_members);
  END IF;
  IF old_count <> root.member_count
  THEN RAISE EXCEPTION 'member storage legacy member count differs'; END IF;

  TRUNCATE pg_temp.st1_down_member_seen;
  member_index := 0;
  previous_slug := NULL;
  FOR block_index IN 0..root.chunk_count-1 LOOP
   block_count := get_byte(root.blocks,block_index*36)::BIGINT*16777216+
    get_byte(root.blocks,block_index*36+1)::BIGINT*65536+
    get_byte(root.blocks,block_index*36+2)::BIGINT*256+get_byte(root.blocks,block_index*36+3);
   IF block_count NOT BETWEEN 1 AND 128 OR (block_index < root.chunk_count-1 AND block_count < 32)
   THEN RAISE EXCEPTION 'member storage block count failure'; END IF;
   SELECT * INTO chunk FROM enterprise_member_chunks WHERE scope_id=owner.scope_id
    AND digest=substring(root.blocks FROM block_index*36+5 FOR 32);
   IF NOT FOUND THEN RAISE EXCEPTION 'member storage chunk missing'; END IF;
   IF chunk.codec <> 1 OR octet_length(chunk.digest) <> 32 OR chunk.count <> block_count
    OR octet_length(chunk.refs)::BIGINT <> block_count*32
   THEN RAISE EXCEPTION 'member storage chunk integrity failure'; END IF;
   chunk_bytes := convert_to('enterprise-member-chunk.v1','UTF8')||nul||int4send(chunk.count);
   FOR ref_index IN 0..chunk.count-1 LOOP
    SELECT * INTO object_row FROM enterprise_member_contents WHERE scope_id=owner.scope_id
     AND digest=substring(chunk.refs FROM ref_index*32+1 FOR 32);
    IF NOT FOUND THEN RAISE EXCEPTION 'member storage content missing'; END IF;
    IF object_row.codec <> 1 OR octet_length(object_row.digest) <> 32 OR object_row.logical_slug=''
    THEN RAISE EXCEPTION 'member storage content integrity failure'; END IF;
    content_bytes := convert_to('enterprise-member-content.v1','UTF8')||nul;
    FOREACH field_value IN ARRAY ARRAY[object_row.kind,object_row.logical_slug,object_row.revision_id,
     object_row.member_digest,object_row.title,object_row.content,object_row.payload_json]
    LOOP
     field_bytes := convert_to(field_value,'UTF8');
     content_bytes := content_bytes||int8send(octet_length(field_bytes)::BIGINT)||field_bytes;
    END LOOP;
    IF pg_catalog.sha256(content_bytes) IS DISTINCT FROM object_row.digest
    THEN RAISE EXCEPTION 'member storage content hash failure'; END IF;
    field_bytes := convert_to(object_row.logical_slug,'UTF8');
    INSERT INTO pg_temp.st1_down_member_seen VALUES(field_bytes) ON CONFLICT DO NOTHING;
    IF NOT FOUND THEN RAISE EXCEPTION 'member storage duplicate slug'; END IF;
    IF root.order_mode='slug_asc' AND previous_slug IS NOT NULL AND previous_slug >= field_bytes
    THEN RAISE EXCEPTION 'member storage internal key order failure'; END IF;
    previous_slug := field_bytes;
    chunk_bytes := chunk_bytes||int8send(octet_length(field_bytes)::BIGINT)||field_bytes||object_row.digest;

    IF owner.owner_type='release' THEN
     -- Release's external SQL collation may differ from internal UTF-8 order.
     -- Match the complete set by exact slug bytes instead of its SQL row order.
     SELECT * INTO old_member FROM wiki_release_members WHERE release_id=owner.owner_id
      AND logical_slug=object_row.logical_slug AND convert_to(logical_slug,'UTF8')=field_bytes;
     IF NOT FOUND OR
      ROW(convert_to(old_member.kind,'UTF8'),convert_to(old_member.logical_slug,'UTF8'),
       convert_to(old_member.revision_id,'UTF8'),convert_to(old_member.member_digest,'UTF8'),
       convert_to(old_member.title,'UTF8'),convert_to(old_member.content,'UTF8'),
       convert_to(old_member.payload::TEXT,'UTF8')) IS DISTINCT FROM
      ROW(convert_to(object_row.kind,'UTF8'),field_bytes,convert_to(object_row.revision_id,'UTF8'),
       convert_to(object_row.member_digest,'UTF8'),convert_to(object_row.title,'UTF8'),
       convert_to(object_row.content,'UTF8'),convert_to(object_row.payload_json,'UTF8'))
     THEN RAISE EXCEPTION 'member storage restored release differs'; END IF;
    ELSE
     old_json := owner.old_members->member_index::INTEGER;
     IF old_json IS DISTINCT FROM jsonb_build_object(
      'kind',object_row.kind,'logical_slug',object_row.logical_slug,'revision_id',object_row.revision_id,
      'member_digest',object_row.member_digest,'title',object_row.title,'content',object_row.content,
      'payload',object_row.payload_json::JSONB)
      OR convert_to((old_json->'payload')::TEXT,'UTF8') IS DISTINCT FROM convert_to(object_row.payload_json,'UTF8')
     THEN RAISE EXCEPTION 'member storage restored preparation differs'; END IF;
    END IF;
    member_index := member_index+1;
   END LOOP;
   IF pg_catalog.sha256(chunk_bytes) IS DISTINCT FROM chunk.digest
   THEN RAISE EXCEPTION 'member storage chunk hash failure'; END IF;
  END LOOP;
  IF member_index <> root.member_count
  THEN RAISE EXCEPTION 'member storage root total differs'; END IF;
 END LOOP;
 DROP TABLE pg_temp.st1_down_member_seen;
 DROP TABLE enterprise_member_validation_failures;
 DROP TABLE enterprise_member_validation_pending;
 DROP TABLE enterprise_member_progress;
 DROP TABLE enterprise_member_preparations;
 DROP TABLE enterprise_member_releases;
 DROP TABLE enterprise_member_sets;
 DROP TABLE enterprise_member_chunks;
 DROP TABLE enterprise_member_contents;
 DROP TABLE enterprise_member_scopes;
 ALTER TABLE wiki_release_preparations DROP COLUMN member_storage;
 ALTER TABLE wiki_releases DROP COLUMN member_storage;
 ALTER TABLE wiki_release_preparations DROP CONSTRAINT enterprise_member_preparation_owner_uk;
 ALTER TABLE wiki_releases DROP CONSTRAINT enterprise_member_release_owner_uk;
END $down$;
