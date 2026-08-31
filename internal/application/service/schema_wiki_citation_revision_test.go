package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

func bindSchemaWikiCitationFixtureToFrozenC5ParentLineage(
	t *testing.T,
	fixture *schemaWikiCitationRevisionFixture,
) {
	t.Helper()
	parent := fixture.chunks.chunk
	receipt := fixture.request.CoordinateAuthorityReceipt
	require.NotNil(t, parent)
	require.NotNil(t, receipt)
	quoteByteStart := strings.Index(parent.Content, fixture.request.Citation.QuoteSnapshot)
	require.GreaterOrEqual(t, quoteByteStart, 0)
	receipt.QuoteOccurrenceStart = utf8.RuneCountInString(parent.Content[:quoteByteStart])
	receipt.QuoteOccurrenceEnd = receipt.QuoteOccurrenceStart +
		utf8.RuneCountInString(fixture.request.Citation.QuoteSnapshot)
	parent.ChunkType = types.ChunkTypeParentText
	parent.ParentChunkID = ""
	parent.EndAt = parent.StartAt + utf8.RuneCountInString(parent.Content)
	child := &types.Chunk{
		ID: "native-child-attempt-119", TenantID: parent.TenantID,
		KnowledgeID: parent.KnowledgeID, KnowledgeBaseID: parent.KnowledgeBaseID,
		ParseAttempt: parent.ParseAttempt, ChunkType: types.ChunkTypeText,
		ParentChunkID: parent.ID, Content: parent.Content, ChunkIndex: 0,
		StartAt: parent.StartAt, EndAt: parent.EndAt,
	}
	fixture.chunks.allChunks = []*types.Chunk{child}
	manifestDigest, err := types.ComputeRevisionManifestDigest(
		parent.KnowledgeID, parent.ParseAttempt,
		[]types.RevisionManifestChunk{{ID: child.ID, Index: child.ChunkIndex, Content: child.Content}},
	)
	require.NoError(t, err)
	pdf := []byte("%PDF-1.7\nfrozen exact C5 source\n%%EOF")
	fileSHA := schemaWikiBytesSHA256(pdf)
	fixture.revisions.revision.FileSHA256 = fileSHA
	fixture.revisions.revision.ManifestDigest = manifestDigest
	fixture.revisions.revision.ChunkCount = 1
	fixture.revisions.source.FileSHA256 = fileSHA
	fixture.revisions.source.Size = int64(len(pdf))
	fixture.revisions.resource.ContentHash = fileSHA
	fixture.revisions.resource.Size = int64(len(pdf))
	revisionSourceID, err := types.ComputeKnowledgeRevisionSourceID(*fixture.revisions.source)
	require.NoError(t, err)
	fixture.revisions.source.RevisionSourceID = revisionSourceID

	roleManifest := map[string]any{
		"contract": "weknora.ec.revision-item.v1", "role": fixture.request.Citation.SourceRole,
		"tenant_id":         fixture.request.Scope.TenantID,
		"knowledge_base_id": fixture.request.Scope.RawKBID,
		"knowledge_id":      parent.KnowledgeID, "weknora_parse_attempt": parent.ParseAttempt,
		"resource_id":            fixture.revisions.source.ResourceID,
		"resource_physical_path": "storage://frozen/native.pdf", "resource_state": "active",
		"resource_binding_count": 1, "file_name": "native.pdf", "file_sha256": fileSHA,
		"file_size": len(pdf), "mime_type": "application/pdf", "material_file": "terms.pdf",
		"page_count": *fixture.revisions.source.PageCount, "parse_status": "completed",
		"parse_completed_at": "2026-08-10T05:36:21Z",
		"parse_identity": map[string]any{
			"app_commit": "test", "app_version": "test", "chunk_overlap": 80,
			"chunk_size": 512, "chunker_config_digest": strings.Repeat("1", 64),
			"docreader": "test", "embedding_model_id": "embedding-test",
			"parser_engine": "builtin", "separators_digest": strings.Repeat("2", 64),
		},
		"parse_manifest_algorithm": types.RevisionManifestAlgorithm,
		"parse_manifest_sha256":    manifestDigest, "chunk_count": 1,
		"ordered_chunk_projection": []any{map[string]any{
			"chunk_id": child.ID, "chunk_index": child.ChunkIndex,
			"content_sha256": schemaWikiStringSHA256(child.Content),
		}},
		"compiler_source_revision_id": revisionSourceID,
	}
	unsigned, err := json.Marshal(roleManifest)
	require.NoError(t, err)
	selfPreimage := append([]byte("weknora.ec.revision-item.v1\x00"), unsigned...)
	selfSum := sha256.Sum256(selfPreimage)
	selfSHA := hex.EncodeToString(selfSum[:])
	roleManifest["manifest_self_sha256"] = selfSHA
	var manifest bytes.Buffer
	encoder := json.NewEncoder(&manifest)
	encoder.SetEscapeHTML(false)
	require.NoError(t, encoder.Encode(roleManifest))

	receipt.SourceSHA256 = fileSHA
	receipt.FileSHA256 = fileSHA
	receipt.WeKnoraManifestDigest = selfSHA
	receipt.ChunkID = parent.ID
	receipt.ChunkIndex = parent.ChunkIndex
	receipt.ChunkContentSHA256 = schemaWikiStringSHA256(parent.Content)
	receipt.LiveRevisionSourceReceipt.RevisionSourceID = revisionSourceID
	receipt.LiveRevisionSourceReceipt.ResourceID = fixture.revisions.source.ResourceID
	receipt.LiveRevisionSourceReceipt.FileSHA256 = fileSHA
	receipt.LiveRevisionSourceReceipt.Size = int64(len(pdf))
	receipt.LiveRevisionSourceReceipt.WeKnoraManifestDigest = selfSHA
	receipt.LiveRevisionSourceReceipt.WeKnoraChunkCount = 1
	liveDigest, err := types.ComputeLiveRevisionSourceReceiptSHA256(receipt.LiveRevisionSourceReceipt)
	require.NoError(t, err)
	receipt.LiveRevisionSourceReceipt.SourceReceiptSHA256 = liveDigest
	receipt.LiveRevisionSourceReceiptSHA256 = liveDigest
	receipt.ReceiptSHA256 = schemaWikiCitationCoordinateAuthorityReceiptSHA256(*receipt)
	fixture.request.Citation.SourceRevisionID = revisionSourceID
	fixture.request.Citation.ChunkID = parent.ID
	fixture.request.frozenNativeSource = &schemaWikiC5FrozenNativeSource{
		experimentID:    "5655e43c-1adb-4282-95f7-305e58441512",
		versionIdentity: strings.Repeat("a", 64), revisionSetSHA256: strings.Repeat("e", 64),
		sourceRole: fixture.request.Citation.SourceRole,
		manifest:   append([]byte(nil), manifest.Bytes()...), sourceBytes: pdf,
	}
	rebindSchemaWikiCitationFixtureToReceipt(t, fixture)
	fixture.revisions.source = nil
	fixture.revisions.resource = nil
}

func replaceSchemaWikiCitationFixtureFrozenC5Children(
	t *testing.T,
	fixture *schemaWikiCitationRevisionFixture,
	children []*types.Chunk,
) {
	t.Helper()
	require.NotEmpty(t, children)
	rows := make([]types.RevisionManifestChunk, len(children))
	projection := make([]any, len(children))
	for index, child := range children {
		require.NotNil(t, child)
		rows[index] = types.RevisionManifestChunk{
			ID: child.ID, Index: child.ChunkIndex, Content: child.Content,
		}
		projection[index] = map[string]any{
			"chunk_id": child.ID, "chunk_index": child.ChunkIndex,
			"content_sha256": schemaWikiStringSHA256(child.Content),
		}
	}
	manifestDigest, err := types.ComputeRevisionManifestDigest(
		fixture.request.Citation.KnowledgeID,
		fixture.revisions.revision.ParseAttempt,
		rows,
	)
	require.NoError(t, err)
	fixture.chunks.allChunks = children
	fixture.revisions.revision.ManifestDigest = manifestDigest
	fixture.revisions.revision.ChunkCount = len(children)

	var roleManifest map[string]any
	require.NoError(t, json.Unmarshal(fixture.request.frozenNativeSource.manifest, &roleManifest))
	delete(roleManifest, "manifest_self_sha256")
	roleManifest["parse_manifest_sha256"] = manifestDigest
	roleManifest["chunk_count"] = len(children)
	roleManifest["ordered_chunk_projection"] = projection
	unsigned, err := json.Marshal(roleManifest)
	require.NoError(t, err)
	selfSum := sha256.Sum256(append([]byte("weknora.ec.revision-item.v1\x00"), unsigned...))
	selfSHA := hex.EncodeToString(selfSum[:])
	roleManifest["manifest_self_sha256"] = selfSHA
	var encoded bytes.Buffer
	encoder := json.NewEncoder(&encoded)
	encoder.SetEscapeHTML(false)
	require.NoError(t, encoder.Encode(roleManifest))
	fixture.request.frozenNativeSource.manifest = append([]byte(nil), encoded.Bytes()...)

	receipt := fixture.request.CoordinateAuthorityReceipt
	require.NotNil(t, receipt)
	receipt.WeKnoraManifestDigest = selfSHA
	receipt.LiveRevisionSourceReceipt.WeKnoraManifestDigest = selfSHA
	receipt.LiveRevisionSourceReceipt.WeKnoraChunkCount = len(children)
	liveDigest, err := types.ComputeLiveRevisionSourceReceiptSHA256(receipt.LiveRevisionSourceReceipt)
	require.NoError(t, err)
	receipt.LiveRevisionSourceReceipt.SourceReceiptSHA256 = liveDigest
	receipt.LiveRevisionSourceReceiptSHA256 = liveDigest
	receipt.ReceiptSHA256 = schemaWikiCitationCoordinateAuthorityReceiptSHA256(*receipt)
	rebindSchemaWikiCitationFixtureToReceipt(t, fixture)
}

func bindSchemaWikiCitationFixtureToFrozenC5OverlappingParentLineage(
	t *testing.T,
	fixture *schemaWikiCitationRevisionFixture,
) (*types.Chunk, *types.Chunk) {
	t.Helper()
	const (
		parentStart = 32892
		parentEnd   = 35726
		quoteStart  = 1220
		quoteEnd    = 1236
	)
	quote := "健康告知内容须如实完整填写并签名"
	require.Equal(t, quoteEnd-quoteStart, utf8.RuneCountInString(quote))
	parentRunes := append(
		append([]rune(strings.Repeat("甲", quoteStart)), []rune(quote)...),
		[]rune(strings.Repeat("乙", parentEnd-parentStart-quoteEnd))...,
	)
	parent := fixture.chunks.chunk
	parent.ID = "482fc89d-c6b5-44cf-a8fa-fbe03b8e41ac"
	parent.Content = string(parentRunes)
	parent.ChunkIndex = 10
	parent.StartAt = parentStart
	parent.EndAt = parentEnd
	fixture.request.FieldID = "health_declaration_requirements"
	fixture.request.Citation.LogicalMemberRef = "field:health_declaration_requirements"
	fixture.request.Citation.PageNumber = 27
	fixture.request.Binding.LogicalMemberRef = fixture.request.Citation.LogicalMemberRef
	fixture.request.Citation.QuoteSnapshot = quote
	fixture.request.Citation.ContentSnapshotSHA256 = schemaWikiStringSHA256(quote)
	fixture.request.Citation.QuoteSHA256 = schemaWikiTestHash(
		t, "schema-wiki-text.v1", map[string]any{"text": quote},
	)
	fixture.request.CoordinateAuthorityReceipt.LocatorContentSHA256 =
		fixture.request.Citation.ContentSnapshotSHA256
	fixture.request.CoordinateAuthorityReceipt.QuoteSHA256 = fixture.request.Citation.QuoteSHA256
	fixture.request.CoordinateAuthorityReceipt.FieldID = fixture.request.FieldID
	fixture.request.CoordinateAuthorityReceipt.NativePageIndex = 26
	fixture.request.CoordinateAuthorityReceipt.PageNumber = 27

	bindSchemaWikiCitationFixtureToFrozenC5ParentLineage(t, fixture)
	parent = fixture.chunks.chunk
	require.Equal(t, quoteStart, fixture.request.CoordinateAuthorityReceipt.QuoteOccurrenceStart)
	require.Equal(t, quoteEnd, fixture.request.CoordinateAuthorityReceipt.QuoteOccurrenceEnd)

	child126Start, child126End := parentStart, 33800
	child127Start, child127End := 33732, 34201
	child128Start, child128End := 34112, 34494
	child129Start, child129End := 34400, parentEnd
	child126 := &types.Chunk{
		ID: "native-child-126", TenantID: parent.TenantID,
		KnowledgeID: parent.KnowledgeID, KnowledgeBaseID: parent.KnowledgeBaseID,
		ParseAttempt: parent.ParseAttempt, ChunkType: types.ChunkTypeText,
		ParentChunkID: parent.ID, ChunkIndex: 126,
		StartAt: child126Start, EndAt: child126End,
		Content: string(parentRunes[child126Start-parentStart : child126End-parentStart]),
	}
	child127 := &types.Chunk{
		ID: "6acf3001-e4d9-4ad6-a0f8-537299e842fa", TenantID: parent.TenantID,
		KnowledgeID: parent.KnowledgeID, KnowledgeBaseID: parent.KnowledgeBaseID,
		ParseAttempt: parent.ParseAttempt, ChunkType: types.ChunkTypeText,
		ParentChunkID: parent.ID, ChunkIndex: 127,
		StartAt: child127Start, EndAt: child127End,
		Content: string(parentRunes[child127Start-parentStart : child127End-parentStart]),
	}
	child128 := &types.Chunk{
		ID: "60d86be4-0a9a-4f0d-b1de-d8c9095dba05", TenantID: parent.TenantID,
		KnowledgeID: parent.KnowledgeID, KnowledgeBaseID: parent.KnowledgeBaseID,
		ParseAttempt: parent.ParseAttempt, ChunkType: types.ChunkTypeText,
		ParentChunkID: parent.ID, ChunkIndex: 128,
		StartAt: child128Start, EndAt: child128End,
		Content: string(parentRunes[child128Start-parentStart : child128End-parentStart]),
	}
	child129 := &types.Chunk{
		ID: "native-child-129", TenantID: parent.TenantID,
		KnowledgeID: parent.KnowledgeID, KnowledgeBaseID: parent.KnowledgeBaseID,
		ParseAttempt: parent.ParseAttempt, ChunkType: types.ChunkTypeText,
		ParentChunkID: parent.ID, ChunkIndex: 129,
		StartAt: child129Start, EndAt: child129End,
		Content: string(parentRunes[child129Start-parentStart : child129End-parentStart]),
	}
	require.Equal(t, 380, utf8.RuneCountInString(
		child127.Content[:strings.Index(child127.Content, quote)],
	))
	require.Zero(t, strings.Index(child128.Content, quote))
	replaceSchemaWikiCitationFixtureFrozenC5Children(
		t, fixture, []*types.Chunk{child126, child127, child128, child129},
	)
	return child127, child128
}

func bindSchemaWikiCitationFixtureToFrozenC5QuoteDomain(
	t *testing.T,
	fixture *schemaWikiCitationRevisionFixture,
	content string,
	quote string,
	start int,
	end int,
) {
	t.Helper()
	fixture.chunks.chunk.Content = content
	fixture.chunks.chunk.StartAt = 0
	fixture.chunks.chunk.EndAt = utf8.RuneCountInString(content)
	fixture.request.Citation.QuoteSnapshot = quote
	fixture.request.Citation.ContentSnapshotSHA256 = schemaWikiStringSHA256(quote)
	fixture.request.Citation.QuoteSHA256 = schemaWikiTestHash(
		t, "schema-wiki-text.v1", map[string]any{"text": quote},
	)
	receipt := fixture.request.CoordinateAuthorityReceipt
	require.NotNil(t, receipt)
	receipt.LocatorContentSHA256 = fixture.request.Citation.ContentSnapshotSHA256
	receipt.QuoteSHA256 = fixture.request.Citation.QuoteSHA256
	receipt.ChunkContentSHA256 = schemaWikiStringSHA256(content)
	receipt.QuoteOccurrenceStart = start
	receipt.QuoteOccurrenceEnd = end
	receipt.QuoteOccurrenceCount = 1
	bindSchemaWikiCitationFixtureToFrozenC5ParentLineage(t, fixture)
}

func bindSchemaWikiCitationFixtureToFrozenC5UnicodeQuote(
	t *testing.T,
	fixture *schemaWikiCitationRevisionFixture,
) (content string, quote string, start int, end int) {
	t.Helper()
	prefix := "投保须知："
	quote = "等待期为三十日。"
	content = prefix + quote + "责任继续有效。"
	start = utf8.RuneCountInString(prefix)
	end = start + utf8.RuneCountInString(quote)
	bindSchemaWikiCitationFixtureToFrozenC5QuoteDomain(
		t, fixture, content, quote, start, end,
	)
	return content, quote, start, end
}

func bindSchemaWikiCitationFixtureToFrozenC5OriginalTextLineage(
	t *testing.T,
	fixture *schemaWikiCitationRevisionFixture,
) {
	t.Helper()
	bindSchemaWikiCitationFixtureToFrozenC5ParentLineage(t, fixture)
	require.Len(t, fixture.chunks.allChunks, 1)
	native := *fixture.chunks.allChunks[0]
	fixture.chunks.chunk = &native
	fixture.chunks.allChunks = []*types.Chunk{&native}
	fixture.request.Citation.ChunkID = native.ID
	receipt := fixture.request.CoordinateAuthorityReceipt
	require.NotNil(t, receipt)
	receipt.ChunkID = native.ID
	receipt.ChunkIndex = native.ChunkIndex
	receipt.ChunkContentSHA256 = schemaWikiStringSHA256(native.Content)
	rehashFrozenC5CitationReceipt(t, fixture)
}

type schemaWikiCitationRevisionRepositoryStub struct {
	knowledge      *types.Knowledge
	revision       *types.KnowledgeRevision
	source         *types.KnowledgeRevisionSource
	resource       *types.StoredResource
	knowledgeCalls int
	revisionCalls  int
	lastAttempt    int64
}

func (s *schemaWikiCitationRevisionRepositoryStub) GetKnowledgeByID(
	_ context.Context, tenantID uint64, knowledgeID string,
) (*types.Knowledge, error) {
	s.knowledgeCalls++
	if s.knowledge == nil || s.knowledge.TenantID != tenantID || s.knowledge.ID != knowledgeID {
		return nil, errors.New("knowledge unavailable")
	}
	copy := *s.knowledge
	return &copy, nil
}

func (s *schemaWikiCitationRevisionRepositoryStub) GetRevision(
	_ context.Context, knowledgeID string, attempt int64,
) (*types.KnowledgeRevision, error) {
	s.revisionCalls++
	s.lastAttempt = attempt
	if s.revision == nil || s.revision.KnowledgeID != knowledgeID || s.revision.ParseAttempt != attempt {
		return nil, errors.New("revision unavailable")
	}
	copy := *s.revision
	return &copy, nil
}

func bindSchemaWikiCitationFixtureToC6NativeIdentity(
	t *testing.T,
	fixture *schemaWikiCitationRevisionFixture,
	evidenceParseAttemptID string,
	weKnoraParseAttempt int64,
) {
	t.Helper()
	receipt := fixture.request.CoordinateAuthorityReceipt
	require.NotNil(t, receipt)
	fixture.revisions.revision.ParseAttempt = weKnoraParseAttempt
	fixture.revisions.source.ParseAttempt = weKnoraParseAttempt
	fixture.chunks.chunk.ParseAttempt = weKnoraParseAttempt
	manifestDigest, err := types.ComputeRevisionManifestDigest(
		fixture.request.Citation.KnowledgeID,
		weKnoraParseAttempt,
		[]types.RevisionManifestChunk{{
			ID: fixture.chunks.chunk.ID, Index: fixture.chunks.chunk.ChunkIndex,
			Content: fixture.chunks.chunk.Content,
		}},
	)
	require.NoError(t, err)
	fixture.revisions.revision.ManifestDigest = manifestDigest
	revisionSourceID, err := types.ComputeKnowledgeRevisionSourceID(*fixture.revisions.source)
	require.NoError(t, err)
	fixture.revisions.source.RevisionSourceID = revisionSourceID

	receipt.EvidenceParseAttemptID = evidenceParseAttemptID
	receipt.WeKnoraParseAttempt = weKnoraParseAttempt
	receipt.WeKnoraManifestDigest = manifestDigest
	receipt.LiveRevisionSourceReceipt.RevisionSourceID = revisionSourceID
	receipt.LiveRevisionSourceReceipt.EvidenceParseAttemptID = evidenceParseAttemptID
	receipt.LiveRevisionSourceReceipt.WeKnoraParseAttempt = weKnoraParseAttempt
	receipt.LiveRevisionSourceReceipt.WeKnoraManifestDigest = manifestDigest
	liveDigest, err := types.ComputeLiveRevisionSourceReceiptSHA256(receipt.LiveRevisionSourceReceipt)
	require.NoError(t, err)
	receipt.LiveRevisionSourceReceipt.SourceReceiptSHA256 = liveDigest
	receipt.LiveRevisionSourceReceiptSHA256 = liveDigest
	receipt.ReceiptSHA256 = schemaWikiCitationCoordinateAuthorityReceiptSHA256(*receipt)

	fixture.request.Citation.SourceRevisionID = revisionSourceID
	fixture.request.Citation.ParseAttemptID = evidenceParseAttemptID
	rebindSchemaWikiCitationFixtureToReceipt(t, fixture)
}

func rebindSchemaWikiCitationFixtureToReceipt(
	t *testing.T,
	fixture *schemaWikiCitationRevisionFixture,
) {
	t.Helper()
	receipt := fixture.request.CoordinateAuthorityReceipt
	require.NotNil(t, receipt)
	fixture.request.Citation.CitationID = "citation-" + receipt.ReceiptSHA256[:24]
	fixture.request.Citation.CitationSHA256 = ""
	fixture.request.Citation.CitationSHA256 = schemaWikiTestHashWithout(
		t, fixture.request.Citation.Contract, fixture.request.Citation, "citation_sha256",
	)
	fixture.request.Binding.CitationSHA256 = fixture.request.Citation.CitationSHA256
	fixture.request.Binding.BindingSHA256 = ""
	fixture.request.Binding.BindingSHA256 = schemaWikiTestHashWithout(
		t, fixture.request.Binding.Contract, fixture.request.Binding, "binding_sha256",
	)
}

func rehashFrozenC5CitationReceipt(
	t *testing.T,
	fixture *schemaWikiCitationRevisionFixture,
) {
	t.Helper()
	receipt := fixture.request.CoordinateAuthorityReceipt
	require.NotNil(t, receipt)
	liveDigest, err := types.ComputeLiveRevisionSourceReceiptSHA256(
		receipt.LiveRevisionSourceReceipt,
	)
	require.NoError(t, err)
	receipt.LiveRevisionSourceReceipt.SourceReceiptSHA256 = liveDigest
	receipt.LiveRevisionSourceReceiptSHA256 = liveDigest
	receipt.ReceiptSHA256 = schemaWikiCitationCoordinateAuthorityReceiptSHA256(*receipt)
	rebindSchemaWikiCitationFixtureToReceipt(t, fixture)
}

func (s *schemaWikiCitationRevisionRepositoryStub) GetRevisionSource(
	_ context.Context, tenantID uint64, knowledgeID string, attempt int64,
) (*types.KnowledgeRevisionSource, *types.StoredResource, error) {
	if s.source == nil || s.resource == nil || s.source.TenantID != tenantID ||
		s.source.KnowledgeID != knowledgeID || s.source.ParseAttempt != attempt ||
		s.source.ResourceID != s.resource.ID {
		return nil, nil, errors.New("revision source unavailable")
	}
	sourceCopy := *s.source
	resourceCopy := *s.resource
	return &sourceCopy, &resourceCopy, nil
}

type schemaWikiCitationChunkRepositoryStub struct {
	chunk     *types.Chunk
	allChunks []*types.Chunk
	getCalls  int
	listCalls int
}

func (s *schemaWikiCitationChunkRepositoryStub) GetChunkByID(
	_ context.Context, tenantID uint64, chunkID string,
) (*types.Chunk, error) {
	s.getCalls++
	if s.chunk == nil || s.chunk.TenantID != tenantID || s.chunk.ID != chunkID {
		return nil, errors.New("chunk unavailable")
	}
	copy := *s.chunk
	return &copy, nil
}

func (s *schemaWikiCitationChunkRepositoryStub) ListChunksByKnowledgeID(
	_ context.Context, tenantID uint64, knowledgeID string,
) ([]*types.Chunk, error) {
	s.listCalls++
	rows := make([]*types.Chunk, 0, len(s.allChunks))
	for _, chunk := range s.allChunks {
		if chunk.TenantID != tenantID || chunk.KnowledgeID != knowledgeID {
			continue
		}
		copy := *chunk
		rows = append(rows, &copy)
	}
	return rows, nil
}

type schemaWikiCitationRevisionFixture struct {
	request   CitationRevisionReadRequestV1
	revisions *schemaWikiCitationRevisionRepositoryStub
	chunks    *schemaWikiCitationChunkRepositoryStub
}

type schemaWikiImmutableRevisionSnapshotReaderStub struct {
	authority    *SchemaWikiCitationPreviewAuthorityV1
	blob         []byte
	err          error
	resolveCalls int
	fetchCalls   int
	requests     []SchemaWikiImmutableRevisionSnapshotRequestV1
	tokens       []string
}

func (s *schemaWikiImmutableRevisionSnapshotReaderStub) ResolveCitationPreviewAuthority(
	_ context.Context,
	request SchemaWikiImmutableRevisionSnapshotRequestV1,
) (*SchemaWikiCitationPreviewAuthorityV1, error) {
	s.resolveCalls++
	s.requests = append(s.requests, request)
	if s.err != nil || s.authority == nil {
		return nil, s.err
	}
	copy := *s.authority
	copy.EvidenceReceiptSHA256s = append([]string(nil), s.authority.EvidenceReceiptSHA256s...)
	return &copy, nil
}

func (s *schemaWikiImmutableRevisionSnapshotReaderStub) ReadByOpaqueToken(
	_ context.Context,
	token string,
) ([]byte, error) {
	s.fetchCalls++
	s.tokens = append(s.tokens, token)
	if s.err != nil {
		return nil, s.err
	}
	return append([]byte(nil), s.blob...), nil
}

type schemaWikiProductionKnowledgeRepositoryStub struct {
	interfaces.KnowledgeRepository
	delegate *schemaWikiCitationRevisionRepositoryStub
}

func (s *schemaWikiProductionKnowledgeRepositoryStub) GetKnowledgeByID(
	ctx context.Context, tenantID uint64, knowledgeID string,
) (*types.Knowledge, error) {
	return s.delegate.GetKnowledgeByID(ctx, tenantID, knowledgeID)
}

func (s *schemaWikiProductionKnowledgeRepositoryStub) GetRevision(
	ctx context.Context, knowledgeID string, attempt int64,
) (*types.KnowledgeRevision, error) {
	return s.delegate.GetRevision(ctx, knowledgeID, attempt)
}

func (s *schemaWikiProductionKnowledgeRepositoryStub) GetRevisionSource(
	ctx context.Context, tenantID uint64, knowledgeID string, attempt int64,
) (*types.KnowledgeRevisionSource, *types.StoredResource, error) {
	return s.delegate.GetRevisionSource(ctx, tenantID, knowledgeID, attempt)
}

type schemaWikiProductionChunkRepositoryStub struct {
	interfaces.ChunkRepository
	delegate *schemaWikiCitationChunkRepositoryStub
}

func (s *schemaWikiProductionChunkRepositoryStub) GetChunkByID(
	ctx context.Context, tenantID uint64, chunkID string,
) (*types.Chunk, error) {
	return s.delegate.GetChunkByID(ctx, tenantID, chunkID)
}

func (s *schemaWikiProductionChunkRepositoryStub) ListChunksByKnowledgeID(
	ctx context.Context, tenantID uint64, knowledgeID string,
) ([]*types.Chunk, error) {
	return s.delegate.ListChunksByKnowledgeID(ctx, tenantID, knowledgeID)
}

func newSchemaWikiCitationRevisionFixture(t *testing.T) schemaWikiCitationRevisionFixture {
	t.Helper()
	release := loadSchemaWikiReleaseVector(t).Release
	citation := firstSchemaWikiCitation(t, release)
	content := "prefix " + citation.QuoteSnapshot + " suffix"
	manifestChunks := []types.RevisionManifestChunk{{
		ID: citation.ChunkID, Index: 0, Content: content,
	}}
	manifestDigest, err := types.ComputeRevisionManifestDigest(citation.KnowledgeID, 119, manifestChunks)
	require.NoError(t, err)
	// ParsedDocument identity is deliberately distinct from the immutable
	// source-file hash. A reader must join both; equating them is not valid.
	citation.ParsedDocumentSHA256 = strings.Repeat("d", 64)
	citation.ParseManifestSHA256 = strings.Repeat("9", 64)
	citation.ContentSnapshotSHA256 = schemaWikiStringSHA256(citation.QuoteSnapshot)
	citation.SourceRevisionID = "revision-119"
	citation.ParseAttemptID = "attempt-119"
	citation.BBox = types.CitationBBoxV1{
		CoordinateSystem: schemaWikiTargetCoordinateSpace,
		PageWidth:        1_000_000, PageHeight: 1_000_000,
		X0: 100_000, Y0: 200_000, X1: 900_000, Y1: 800_000,
	}
	citation.CitationSHA256 = ""
	citation.CitationSHA256 = schemaWikiTestHashWithout(
		t, citation.Contract, citation, "citation_sha256",
	)
	binding := types.CitationMemberBindingV1{
		Contract:         "citation-member-binding.v1",
		CitationSHA256:   citation.CitationSHA256,
		LogicalMemberRef: citation.LogicalMemberRef,
		MemberDigest:     strings.Repeat("b", 64),
	}
	binding.BindingSHA256 = schemaWikiTestHashWithout(
		t, binding.Contract, binding, "binding_sha256",
	)
	scope := types.WikiReleaseScope{
		TenantID: 10003, SpaceID: citation.SpaceID,
		RawKBID: "raw-medical-596-1", WikiKBID: "wiki-medical-596-1",
	}
	pageCount := 39
	resource := &types.StoredResource{
		ID: "resource-attempt-119", TenantID: scope.TenantID,
		Provider: "local", PhysicalPath: "local://immutable/attempt-119.pdf",
		Kind: "file", MimeType: "application/pdf", Size: 4096,
		ContentHash: strings.Repeat("e", 64),
		Lifecycle:   types.ResourceLifecyclePersistent, State: types.ResourceStateActive,
	}
	source := &types.KnowledgeRevisionSource{
		TenantID: scope.TenantID, KnowledgeID: citation.KnowledgeID, ParseAttempt: 119,
		ResourceID: resource.ID, FileSHA256: resource.ContentHash,
		Size: resource.Size, MimeType: resource.MimeType, PageCount: &pageCount,
		RetentionState: types.KnowledgeRevisionSourcePinned,
	}
	revisionSourceID, err := types.ComputeKnowledgeRevisionSourceID(*source)
	require.NoError(t, err)
	source.RevisionSourceID = revisionSourceID
	liveReceipt := types.LiveRevisionSourceReceiptV1{
		Contract:         "live-revision-source-receipt.v1",
		RevisionSourceID: source.RevisionSourceID,
		TenantID:         scope.TenantID, SpaceID: scope.SpaceID,
		RawKBID: scope.RawKBID, WikiKBID: scope.WikiKBID,
		KnowledgeID:            citation.KnowledgeID,
		EvidenceParseAttemptID: citation.ParseAttemptID,
		WeKnoraParseAttempt:    119, ResourceID: source.ResourceID,
		FileSHA256: source.FileSHA256, Size: source.Size, MimeType: source.MimeType,
		PageCount: pageCount, ParsedDocumentSHA256: citation.ParsedDocumentSHA256,
		ParseManifestSHA256:      citation.ParseManifestSHA256,
		WeKnoraManifestAlgorithm: types.RevisionManifestAlgorithm,
		WeKnoraManifestDigest:    manifestDigest, WeKnoraChunkCount: 1,
	}
	liveReceiptSHA256, err := types.ComputeLiveRevisionSourceReceiptSHA256(liveReceipt)
	require.NoError(t, err)
	liveReceipt.SourceReceiptSHA256 = liveReceiptSHA256
	quoteStart := strings.Index(content, citation.QuoteSnapshot)
	coordinateReceipt := &SchemaWikiCitationCoordinateAuthorityReceiptV1{
		Contract:        "schema67-citation-authority-join-receipt.v1",
		CandidateSHA256: strings.Repeat("6", 64), FieldID: "product_code",
		SourceRole:             citation.SourceRole,
		EvidenceReceiptSHA256:  strings.Repeat("7", 64),
		SourceSHA256:           source.FileSHA256,
		ParsedDocumentSHA256:   citation.ParsedDocumentSHA256,
		ParseManifestSHA256:    citation.ParseManifestSHA256,
		EvidenceParseAttemptID: citation.ParseAttemptID,
		LocatorKind:            "block", LocatorRef: citation.LocatorRef,
		NativePageIndex: citation.PageNumber - 1, PageNumber: citation.PageNumber,
		LocatorContentSHA256:     citation.ContentSnapshotSHA256,
		QuoteSHA256:              citation.QuoteSHA256,
		CaptureIdentitySHA256:    strings.Repeat("1", 64),
		RawStructureSHA256:       strings.Repeat("2", 64),
		SanitizedStructureSHA256: strings.Repeat("3", 64),
		ParserIdentitySHA256:     strings.Repeat("4", 64),
		CoordinatePolicySHA256:   schemaWikiCoordinatePolicySHA256,
		SourceCoordinateSpace:    schemaWikiSourceCoordinateSpace,
		TargetCoordinateSpace:    schemaWikiTargetCoordinateSpace,
		Origin:                   "top_left", SourceBBoxPreimage: [4]string{"100", "200", "900", "800"},
		NormalizedBBox: citation.BBox, PageWidth: 1_000_000, PageHeight: 1_000_000,
		RotationDegrees: 0, HighlightPrecision: "locator_exact",
		TenantID: scope.TenantID, SpaceID: scope.SpaceID, RawKBID: scope.RawKBID,
		KnowledgeID: citation.KnowledgeID, WeKnoraParseAttempt: 119,
		FileSHA256:               source.FileSHA256,
		WeKnoraManifestAlgorithm: types.RevisionManifestAlgorithm,
		WeKnoraManifestDigest:    manifestDigest,
		ChunkID:                  citation.ChunkID, ChunkIndex: 0,
		ChunkContentSHA256:              schemaWikiStringSHA256(content),
		QuoteOccurrenceStart:            quoteStart,
		QuoteOccurrenceEnd:              quoteStart + len(citation.QuoteSnapshot),
		QuoteOccurrenceCount:            1,
		JoinPolicySHA256:                types.Schema67JoinPolicySHA256,
		LiveRevisionSourceReceipt:       liveReceipt,
		LiveRevisionSourceReceiptSHA256: liveReceiptSHA256,
	}
	coordinateReceipt.ReceiptSHA256 = schemaWikiCitationCoordinateAuthorityReceiptSHA256(*coordinateReceipt)
	return schemaWikiCitationRevisionFixture{
		request: CitationRevisionReadRequestV1{
			ReleaseID: "release-596-1-v1", ActivationEpoch: 1,
			CandidateSHA256: strings.Repeat("6", 64), FieldID: "product_code",
			Scope: scope, Citation: citation, Binding: binding,
			EvidenceReceiptSHA256s:     []string{strings.Repeat("7", 64)},
			CoordinateAuthorityReceipt: coordinateReceipt,
		},
		revisions: &schemaWikiCitationRevisionRepositoryStub{
			knowledge: &types.Knowledge{
				ID: citation.KnowledgeID, TenantID: scope.TenantID,
				KnowledgeBaseID: scope.RawKBID, ParseStatus: types.ParseStatusCompleted,
				CurrentParseAttempt: 120, FileType: "pdf",
				FilePath:   "resource://CURRENT_POINTER_MUST_NOT_BE_READ",
				FileSHA256: strings.Repeat("c", 64),
			},
			revision: &types.KnowledgeRevision{
				KnowledgeID: citation.KnowledgeID, ParseAttempt: 119,
				FileSHA256:        strings.Repeat("e", 64),
				ManifestAlgorithm: types.RevisionManifestAlgorithm,
				ManifestDigest:    manifestDigest, ChunkCount: 1,
			},
			source:   source,
			resource: resource,
		},
		chunks: &schemaWikiCitationChunkRepositoryStub{chunk: &types.Chunk{
			ID: citation.ChunkID, TenantID: scope.TenantID,
			KnowledgeID: citation.KnowledgeID, KnowledgeBaseID: scope.RawKBID,
			ParseAttempt: 119, ChunkType: types.ChunkTypeText,
			Content: content, ChunkIndex: 0, StartAt: 0, EndAt: len(content),
		}},
	}
}

func schemaWikiCitationPreviewAuthorityForFixture(
	t *testing.T,
	fixture schemaWikiCitationRevisionFixture,
	blob []byte,
) *SchemaWikiCitationPreviewAuthorityV1 {
	t.Helper()
	require.NotEmpty(t, blob)
	receipt := *fixture.request.CoordinateAuthorityReceipt
	liveReceipt := types.LiveRevisionSourceReceiptV1{
		Contract:         "live-revision-source-receipt.v1",
		RevisionSourceID: fixture.revisions.source.RevisionSourceID,
		TenantID:         fixture.request.Scope.TenantID, SpaceID: fixture.request.Scope.SpaceID,
		RawKBID: fixture.request.Scope.RawKBID, WikiKBID: fixture.request.Scope.WikiKBID,
		KnowledgeID:            fixture.request.Citation.KnowledgeID,
		EvidenceParseAttemptID: receipt.EvidenceParseAttemptID,
		WeKnoraParseAttempt:    fixture.revisions.revision.ParseAttempt,
		ResourceID:             fixture.revisions.source.ResourceID,
		FileSHA256:             fixture.revisions.source.FileSHA256,
		Size:                   fixture.revisions.source.Size, MimeType: fixture.revisions.source.MimeType,
		PageCount:                *fixture.revisions.source.PageCount,
		ParsedDocumentSHA256:     receipt.ParsedDocumentSHA256,
		ParseManifestSHA256:      receipt.ParseManifestSHA256,
		WeKnoraManifestAlgorithm: fixture.revisions.revision.ManifestAlgorithm,
		WeKnoraManifestDigest:    fixture.revisions.revision.ManifestDigest,
		WeKnoraChunkCount:        fixture.revisions.revision.ChunkCount,
		SourceReceiptSHA256:      receipt.LiveRevisionSourceReceiptSHA256,
	}
	request := SchemaWikiImmutableRevisionSnapshotRequestV1{
		Contract:             "schema-wiki-immutable-revision-snapshot-request.v1",
		ReleaseID:            fixture.request.ReleaseID,
		ActivationEpoch:      fixture.request.ActivationEpoch,
		PreparationID:        fixture.request.PreparationID,
		EvaluationID:         fixture.request.EvaluationID,
		EvidenceID:           fixture.request.EvidenceID,
		Scope:                fixture.request.Scope,
		CandidateSHA256:      fixture.request.CandidateSHA256,
		LogicalMemberRef:     fixture.request.Citation.LogicalMemberRef,
		FieldID:              fixture.request.FieldID,
		CitationID:           fixture.request.Citation.CitationID,
		CitationSHA256:       fixture.request.Citation.CitationSHA256,
		BindingSHA256:        fixture.request.Binding.BindingSHA256,
		KnowledgeID:          fixture.request.Citation.KnowledgeID,
		ParseAttempt:         fixture.revisions.revision.ParseAttempt,
		ResourceID:           fixture.revisions.source.ResourceID,
		FileSHA256:           fixture.revisions.revision.FileSHA256,
		Size:                 fixture.revisions.source.Size,
		MimeType:             fixture.revisions.source.MimeType,
		ManifestAlgorithm:    types.RevisionManifestAlgorithm,
		ManifestDigest:       fixture.revisions.revision.ManifestDigest,
		ChunkCount:           fixture.revisions.revision.ChunkCount,
		ParsedDocumentSHA256: fixture.request.Citation.ParsedDocumentSHA256,
		EvidenceReceiptSHA256s: append(
			[]string(nil), fixture.request.EvidenceReceiptSHA256s...,
		),
		CoordinateReceipt: receipt,
		LiveSourceReceipt: liveReceipt,
	}
	authority := &SchemaWikiCitationPreviewAuthorityV1{
		Contract:               "schema-wiki-citation-preview-authority.v1",
		Request:                request,
		FieldID:                strings.TrimPrefix(fixture.request.Citation.LogicalMemberRef, "field:"),
		ChunkID:                fixture.request.Citation.ChunkID,
		LocatorRef:             fixture.request.Citation.LocatorRef,
		PageNumber:             fixture.request.Citation.PageNumber,
		BBox:                   fixture.request.Citation.BBox,
		CoordinateSpaceVersion: schemaWikiTargetCoordinateSpace,
		PageWidth:              fixture.request.Citation.BBox.PageWidth,
		PageHeight:             fixture.request.Citation.BBox.PageHeight,
		RotationDegrees:        0,
		QuoteSHA256:            fixture.request.Citation.QuoteSHA256,
		ContentSnapshotSHA256:  fixture.request.Citation.ContentSnapshotSHA256,
		EvidenceReceiptSHA256s: append(
			[]string(nil), fixture.request.EvidenceReceiptSHA256s...,
		),
		OpaqueToken: "opaque-token-attempt-119",
	}
	authority.AuthoritySHA256 = schemaWikiCitationPreviewAuthoritySHA256(*authority)
	return authority
}

func TestSchemaWikiCitationRevisionAdapterReopensFrozenC5ParentTextThroughExactNativeChild(t *testing.T) {
	fixture := newSchemaWikiCitationRevisionFixture(t)
	bindSchemaWikiCitationFixtureToFrozenC5ParentLineage(t, &fixture)
	adapter := newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks)
	authority, err := adapter.resolveExactRevisionAuthority(
		context.WithValue(context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID),
		fixture.request,
	)
	require.NoError(t, err)
	require.NotNil(t, authority)
	require.Equal(t, fixture.request.Citation.ChunkID, authority.ChunkID,
		"public authority keeps the original persisted parent_text identity")
	require.Equal(t, fixture.revisions.revision.ManifestDigest, authority.Request.ManifestDigest,
		"native text manifest is a distinct internal authority domain")
	require.Equal(t,
		fixture.request.CoordinateAuthorityReceipt.WeKnoraManifestDigest,
		authority.Request.LiveSourceReceipt.WeKnoraManifestDigest,
		"returned source authority keeps the frozen C1 entry identity")
	require.NotEqual(t,
		authority.Request.ManifestDigest,
		authority.Request.LiveSourceReceipt.WeKnoraManifestDigest,
	)
}

func TestSchemaWikiCitationRevisionAdapterReopensFrozenC5OverlappingChildrenAtOneSourceOccurrence(
	t *testing.T,
) {
	for _, readPath := range []struct {
		name  string
		apply func(*CitationRevisionReadRequestV1)
	}{
		{name: "current", apply: func(*CitationRevisionReadRequestV1) {}},
		{name: "explicit pinned", apply: func(request *CitationRevisionReadRequestV1) {
			request.ReleaseID = "release-pinned-overlap"
			request.ActivationEpoch = 2
		}},
	} {
		t.Run(readPath.name, func(t *testing.T) {
			fixture := newSchemaWikiCitationRevisionFixture(t)
			child127, child128 := bindSchemaWikiCitationFixtureToFrozenC5OverlappingParentLineage(
				t, &fixture,
			)
			quote := fixture.request.Citation.QuoteSnapshot
			parentOccurrence := fixture.chunks.chunk.StartAt +
				fixture.request.CoordinateAuthorityReceipt.QuoteOccurrenceStart
			child127Occurrence := child127.StartAt + utf8.RuneCountInString(
				child127.Content[:strings.Index(child127.Content, quote)],
			)
			child128Occurrence := child128.StartAt + utf8.RuneCountInString(
				child128.Content[:strings.Index(child128.Content, quote)],
			)
			require.Equal(t, 34112, parentOccurrence)
			require.Equal(t, parentOccurrence, child127Occurrence)
			require.Equal(t, parentOccurrence, child128Occurrence)
			owner, ok := schemaWikiC5CanonicalTextForParentOccurrence(
				fixture.chunks.chunk,
				fixture.chunks.allChunks,
				quote,
				fixture.request.CoordinateAuthorityReceipt,
			)
			require.True(t, ok)
			require.Equal(t, child127.ID, owner.ID,
				"the reconstruction frontier owns the shared source occurrence")
			readPath.apply(&fixture.request)

			adapter := newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks)
			authority, err := adapter.resolveExactRevisionAuthority(
				context.WithValue(
					context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID,
				),
				fixture.request,
			)
			require.NoError(t, err)
			require.NotNil(t, authority)
			require.Equal(t, fixture.chunks.chunk.ID, authority.ChunkID,
				"public authority remains the persisted parent_text identity")
		})
	}
}

func TestSchemaWikiCitationRevisionAdapterRejectsInvalidFrozenC5OverlapOwnership(t *testing.T) {
	tests := map[string]func(*schemaWikiCitationRevisionFixture, *types.Chunk, *types.Chunk){
		"different absolute source occurrence": func(
			_ *schemaWikiCitationRevisionFixture, _ *types.Chunk, child128 *types.Chunk,
		) {
			child128.StartAt++
			child128.EndAt++
		},
		"no unique contribution owner": func(
			_ *schemaWikiCitationRevisionFixture, child127 *types.Chunk, child128 *types.Chunk,
		) {
			child128.StartAt = child127.StartAt
			child128.EndAt = child127.EndAt
			child128.Content = child127.Content
		},
		"mixed byte and code point offset": func(
			fixture *schemaWikiCitationRevisionFixture, child127 *types.Chunk, _ *types.Chunk,
		) {
			quote := fixture.request.Citation.QuoteSnapshot
			byteOffset := strings.Index(child127.Content, quote)
			codePointOffset := utf8.RuneCountInString(child127.Content[:byteOffset])
			child127.StartAt += byteOffset - codePointOffset
			child127.EndAt += byteOffset - codePointOffset
		},
		"parent boundary drift": func(
			fixture *schemaWikiCitationRevisionFixture, _ *types.Chunk, _ *types.Chunk,
		) {
			fixture.chunks.chunk.EndAt--
		},
		"child content drift": func(
			_ *schemaWikiCitationRevisionFixture, child127 *types.Chunk, _ *types.Chunk,
		) {
			child127.Content += " changed"
		},
		"child parent drift": func(
			_ *schemaWikiCitationRevisionFixture, _ *types.Chunk, child128 *types.Chunk,
		) {
			child128.ParentChunkID = "foreign-parent"
		},
		"child index drift": func(
			_ *schemaWikiCitationRevisionFixture, _ *types.Chunk, child128 *types.Chunk,
		) {
			child128.ChunkIndex++
		},
		"native manifest drift": func(
			fixture *schemaWikiCitationRevisionFixture, _ *types.Chunk, _ *types.Chunk,
		) {
			fixture.revisions.revision.ManifestDigest = strings.Repeat("9", 64)
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			fixture := newSchemaWikiCitationRevisionFixture(t)
			child127, child128 := bindSchemaWikiCitationFixtureToFrozenC5OverlappingParentLineage(
				t, &fixture,
			)
			mutate(&fixture, child127, child128)
			adapter := newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks)
			authority, err := adapter.resolveExactRevisionAuthority(
				context.WithValue(
					context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID,
				),
				fixture.request,
			)
			require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
			require.Nil(t, authority)
		})
	}
}

func TestSchemaWikiCitationRevisionAdapterReopensFrozenC5OriginalTextMembership(t *testing.T) {
	fixture := newSchemaWikiCitationRevisionFixture(t)
	bindSchemaWikiCitationFixtureToFrozenC5OriginalTextLineage(t, &fixture)
	adapter := newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks)
	authority, err := adapter.resolveExactRevisionAuthority(
		context.WithValue(
			context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID,
		),
		fixture.request,
	)
	require.NoError(t, err)
	require.NotNil(t, authority)
	require.Equal(t, fixture.chunks.chunk.ID, authority.ChunkID)
}

func TestSchemaWikiCitationRevisionAdapterReopensPersistedUnicodeCodePointOffsetsForFrozenC5(t *testing.T) {
	for _, readPath := range []struct {
		name  string
		apply func(*CitationRevisionReadRequestV1)
	}{
		{name: "current", apply: func(*CitationRevisionReadRequestV1) {}},
		{name: "explicit pinned", apply: func(request *CitationRevisionReadRequestV1) {
			request.ReleaseID = "release-pinned-unicode"
			request.ActivationEpoch = 2
		}},
	} {
		t.Run(readPath.name, func(t *testing.T) {
			fixture := newSchemaWikiCitationRevisionFixture(t)
			content, quote, start, end := bindSchemaWikiCitationFixtureToFrozenC5UnicodeQuote(
				t, &fixture,
			)
			require.Equal(t, 5, start)
			require.Equal(t, 13, end)
			require.Greater(t, strings.Index(content, quote), start,
				"the persisted producer offsets are code points, not UTF-8 bytes")
			readPath.apply(&fixture.request)
			adapter := newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks)
			authority, err := adapter.resolveExactRevisionAuthority(
				context.WithValue(
					context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID,
				),
				fixture.request,
			)
			require.NoError(t, err)
			require.NotNil(t, authority)
			require.Equal(t, fixture.request.CoordinateAuthorityReceipt.ReceiptSHA256[:24],
				fixture.request.Citation.CitationID[len("citation-"):])
		})
	}
}

func TestSchemaWikiCitationRevisionAdapterKeepsFrozenC5ASCIIQuoteCompatible(t *testing.T) {
	fixture := newSchemaWikiCitationRevisionFixture(t)
	prefix := "prefix: "
	quote := "waiting period is thirty days"
	content := prefix + quote + "."
	start := len(prefix)
	bindSchemaWikiCitationFixtureToFrozenC5QuoteDomain(
		t, &fixture, content, quote, start, start+len(quote),
	)
	adapter := newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks)
	authority, err := adapter.resolveExactRevisionAuthority(
		context.WithValue(
			context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID,
		),
		fixture.request,
	)
	require.NoError(t, err)
	require.NotNil(t, authority)
}

func TestSchemaWikiCitationRevisionAdapterRejectsInvalidFrozenC5UnicodeOffsetDomains(t *testing.T) {
	tests := map[string]func(*testing.T, *schemaWikiCitationRevisionFixture, string, string){
		"utf8 byte offsets presented as code points": func(
			t *testing.T, fixture *schemaWikiCitationRevisionFixture, content string, quote string,
		) {
			start := strings.Index(content, quote)
			fixture.request.CoordinateAuthorityReceipt.QuoteOccurrenceStart = start
			fixture.request.CoordinateAuthorityReceipt.QuoteOccurrenceEnd = start + len(quote)
			rehashFrozenC5CitationReceipt(t, fixture)
		},
		"range ends inside the persisted quote": func(
			t *testing.T, fixture *schemaWikiCitationRevisionFixture, _ string, _ string,
		) {
			fixture.request.CoordinateAuthorityReceipt.QuoteOccurrenceEnd--
			rehashFrozenC5CitationReceipt(t, fixture)
		},
		"code point range out of bounds": func(
			t *testing.T, fixture *schemaWikiCitationRevisionFixture, content string, _ string,
		) {
			fixture.request.CoordinateAuthorityReceipt.QuoteOccurrenceEnd =
				utf8.RuneCountInString(content) + 1
			rehashFrozenC5CitationReceipt(t, fixture)
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			fixture := newSchemaWikiCitationRevisionFixture(t)
			content, quote, _, _ := bindSchemaWikiCitationFixtureToFrozenC5UnicodeQuote(t, &fixture)
			mutate(t, &fixture, content, quote)
			require.NoError(t, types.ValidateSchema67CitationAuthorityJoinReceiptV1(
				*fixture.request.CoordinateAuthorityReceipt,
			))
			adapter := newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks)
			authority, err := adapter.resolveExactRevisionAuthority(
				context.WithValue(
					context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID,
				),
				fixture.request,
			)
			require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
			require.Nil(t, authority)
		})
	}

	t.Run("quote appears more than once", func(t *testing.T) {
		fixture := newSchemaWikiCitationRevisionFixture(t)
		quote := "等待期为三十日。"
		prefix := "投保须知："
		content := prefix + quote + "另见：" + quote
		start := utf8.RuneCountInString(prefix)
		bindSchemaWikiCitationFixtureToFrozenC5QuoteDomain(
			t, &fixture, content, quote, start, start+utf8.RuneCountInString(quote),
		)
		adapter := newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks)
		authority, err := adapter.resolveExactRevisionAuthority(
			context.WithValue(
				context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID,
			),
			fixture.request,
		)
		require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
		require.Nil(t, authority)
	})

	t.Run("chunk contains a partial utf8 character", func(t *testing.T) {
		fixture := newSchemaWikiCitationRevisionFixture(t)
		quote := "exact ASCII quote"
		content := "prefix" + string([]byte{0xe4, 0xb8}) + quote
		start := utf8.RuneCountInString(content) - utf8.RuneCountInString(quote)
		bindSchemaWikiCitationFixtureToFrozenC5QuoteDomain(
			t, &fixture, content, quote, start, start+utf8.RuneCountInString(quote),
		)
		adapter := newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks)
		authority, err := adapter.resolveExactRevisionAuthority(
			context.WithValue(
				context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID,
			),
			fixture.request,
		)
		require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
		require.Nil(t, authority)
	})
}

func TestSchemaWikiCitationRevisionAdapterLegacyLivePathKeepsUnicodeByteOffsets(t *testing.T) {
	fixture := newSchemaWikiCitationRevisionFixture(t)
	prefix := "投保须知："
	quote := "等待期为三十日。"
	content := prefix + quote + "责任继续有效。"
	fixture.chunks.chunk.Content = content
	fixture.chunks.chunk.StartAt = 0
	fixture.chunks.chunk.EndAt = len(content)
	fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
	fixture.request.Citation.QuoteSnapshot = quote
	fixture.request.Citation.ContentSnapshotSHA256 = schemaWikiStringSHA256(quote)
	fixture.request.Citation.QuoteSHA256 = schemaWikiTestHash(
		t, "schema-wiki-text.v1", map[string]any{"text": quote},
	)
	receipt := fixture.request.CoordinateAuthorityReceipt
	require.NotNil(t, receipt)
	receipt.LocatorContentSHA256 = fixture.request.Citation.ContentSnapshotSHA256
	receipt.QuoteSHA256 = fixture.request.Citation.QuoteSHA256
	receipt.ChunkContentSHA256 = schemaWikiStringSHA256(content)
	receipt.QuoteOccurrenceStart = strings.Index(content, quote)
	receipt.QuoteOccurrenceEnd = receipt.QuoteOccurrenceStart + len(quote)
	manifestDigest, err := types.ComputeRevisionManifestDigest(
		fixture.request.Citation.KnowledgeID, fixture.revisions.revision.ParseAttempt,
		[]types.RevisionManifestChunk{{
			ID: fixture.chunks.chunk.ID, Index: fixture.chunks.chunk.ChunkIndex, Content: content,
		}},
	)
	require.NoError(t, err)
	fixture.revisions.revision.ManifestDigest = manifestDigest
	receipt.WeKnoraManifestDigest = manifestDigest
	receipt.LiveRevisionSourceReceipt.WeKnoraManifestDigest = manifestDigest
	rehashFrozenC5CitationReceipt(t, &fixture)
	require.NoError(t, types.ValidateCitationTarget(fixture.request.Citation))
	require.NoError(t, validateSchemaWikiCitationCoordinateAuthorityReceipt(
		fixture.request, *receipt, fixture.revisions.revision,
		fixture.revisions.source, fixture.chunks.chunk,
	))
}

func TestSchemaWikiCitationRevisionAdapterRejectsFrozenC5NativeCustodyDrift(t *testing.T) {
	tests := map[string]func(*testing.T, *schemaWikiCitationRevisionFixture){
		"self hash and native manifest domain swapped": func(t *testing.T, f *schemaWikiCitationRevisionFixture) {
			f.request.CoordinateAuthorityReceipt.WeKnoraManifestDigest = f.revisions.revision.ManifestDigest
			f.request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt.WeKnoraManifestDigest =
				f.revisions.revision.ManifestDigest
			rehashFrozenC5CitationReceipt(t, f)
		},
		"parent has no child": func(_ *testing.T, f *schemaWikiCitationRevisionFixture) {
			f.chunks.allChunks = nil
		},
		"parent leaks into canonical text membership": func(
			_ *testing.T, f *schemaWikiCitationRevisionFixture,
		) {
			f.chunks.allChunks = append([]*types.Chunk{f.chunks.chunk}, f.chunks.allChunks...)
		},
		"parent has multiple children": func(_ *testing.T, f *schemaWikiCitationRevisionFixture) {
			duplicate := *f.chunks.allChunks[0]
			duplicate.ID = "second-native-child"
			duplicate.ChunkIndex = 1
			f.chunks.allChunks = append(f.chunks.allChunks, &duplicate)
		},
		"wrong child parent": func(_ *testing.T, f *schemaWikiCitationRevisionFixture) {
			f.chunks.allChunks[0].ParentChunkID = "foreign-parent"
		},
		"parent kind drift": func(_ *testing.T, f *schemaWikiCitationRevisionFixture) {
			f.chunks.chunk.ChunkType = types.ChunkTypeImageOCR
		},
		"knowledge drift": func(_ *testing.T, f *schemaWikiCitationRevisionFixture) {
			f.chunks.allChunks[0].KnowledgeID = "foreign-knowledge"
		},
		"chunk drift": func(_ *testing.T, f *schemaWikiCitationRevisionFixture) {
			f.chunks.allChunks[0].Content += " changed"
		},
		"file drift": func(_ *testing.T, f *schemaWikiCitationRevisionFixture) {
			f.request.frozenNativeSource.sourceBytes = append(
				f.request.frozenNativeSource.sourceBytes, 'x',
			)
		},
		"page drift": func(_ *testing.T, f *schemaWikiCitationRevisionFixture) {
			f.request.CoordinateAuthorityReceipt.PageNumber++
		},
		"bbox drift": func(_ *testing.T, f *schemaWikiCitationRevisionFixture) {
			f.request.CoordinateAuthorityReceipt.NormalizedBBox.X0++
		},
		"quote drift": func(_ *testing.T, f *schemaWikiCitationRevisionFixture) {
			f.request.Citation.QuoteSnapshot = "foreign quote"
		},
		"native manifest drift": func(_ *testing.T, f *schemaWikiCitationRevisionFixture) {
			f.revisions.revision.ManifestDigest = strings.Repeat("9", 64)
		},
		"revision source drift after full rehash": func(t *testing.T, f *schemaWikiCitationRevisionFixture) {
			foreign := strings.Repeat("f", 64)
			f.request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt.RevisionSourceID = foreign
			f.request.Citation.SourceRevisionID = foreign
			rehashFrozenC5CitationReceipt(t, f)
		},
		"resource drift after full rehash": func(t *testing.T, f *schemaWikiCitationRevisionFixture) {
			f.request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt.ResourceID = "resource-foreign"
			rehashFrozenC5CitationReceipt(t, f)
		},
		"parse attempt drift after full rehash": func(t *testing.T, f *schemaWikiCitationRevisionFixture) {
			f.request.CoordinateAuthorityReceipt.WeKnoraParseAttempt++
			f.request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt.WeKnoraParseAttempt++
			rehashFrozenC5CitationReceipt(t, f)
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			fixture := newSchemaWikiCitationRevisionFixture(t)
			bindSchemaWikiCitationFixtureToFrozenC5ParentLineage(t, &fixture)
			mutate(t, &fixture)
			adapter := newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks)
			authority, err := adapter.resolveExactRevisionAuthority(
				context.WithValue(context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID),
				fixture.request,
			)
			require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
			require.Nil(t, authority)
		})
	}
}

func TestSchemaWikiCitationRevisionAdapterResolvesTwoPhaseAuthorityButFailsClosedBeforeTokenFetch(t *testing.T) {
	t.Parallel()
	fixture := newSchemaWikiCitationRevisionFixture(t)
	fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
	blob := []byte("%PDF-1.7\nimmutable attempt 119\n%%EOF")
	authority := schemaWikiCitationPreviewAuthorityForFixture(t, fixture, blob)
	reader := &schemaWikiImmutableRevisionSnapshotReaderStub{authority: authority, blob: blob}
	adapter := newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks, reader)
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(10003))

	opened, err := adapter.ReadExactRevision(ctx, fixture.request)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
	require.Empty(t, opened)
	require.Equal(t, 1, reader.resolveCalls)
	require.Zero(t, reader.fetchCalls)
	require.Equal(t, []SchemaWikiImmutableRevisionSnapshotRequestV1{authority.Request}, reader.requests)
	require.NotEqual(t, authority.Request.FileSHA256, authority.Request.ParsedDocumentSHA256)
	require.Equal(t, authority.BBox.PageWidth, authority.PageWidth)
	require.Equal(t, authority.BBox.PageHeight, authority.PageHeight)
	require.NotEmpty(t, authority.CoordinateSpaceVersion)
	require.Empty(t, reader.tokens)
}

func TestSchemaWikiCitationRevisionAdapterRejectsRehashedSnapshotAuthorityDrift(t *testing.T) {
	t.Parallel()
	tests := map[string]func(*SchemaWikiCitationPreviewAuthorityV1){
		"release":     func(a *SchemaWikiCitationPreviewAuthorityV1) { a.Request.ReleaseID = "foreign" },
		"epoch":       func(a *SchemaWikiCitationPreviewAuthorityV1) { a.Request.ActivationEpoch++ },
		"tenant":      func(a *SchemaWikiCitationPreviewAuthorityV1) { a.Request.Scope.TenantID++ },
		"space":       func(a *SchemaWikiCitationPreviewAuthorityV1) { a.Request.Scope.SpaceID = "foreign" },
		"raw kb":      func(a *SchemaWikiCitationPreviewAuthorityV1) { a.Request.Scope.RawKBID = "foreign" },
		"wiki kb":     func(a *SchemaWikiCitationPreviewAuthorityV1) { a.Request.Scope.WikiKBID = "foreign" },
		"knowledge":   func(a *SchemaWikiCitationPreviewAuthorityV1) { a.Request.KnowledgeID = "foreign" },
		"attempt":     func(a *SchemaWikiCitationPreviewAuthorityV1) { a.Request.ParseAttempt++ },
		"file digest": func(a *SchemaWikiCitationPreviewAuthorityV1) { a.Request.FileSHA256 = strings.Repeat("a", 64) },
		"manifest":    func(a *SchemaWikiCitationPreviewAuthorityV1) { a.Request.ManifestDigest = strings.Repeat("a", 64) },
		"count":       func(a *SchemaWikiCitationPreviewAuthorityV1) { a.Request.ChunkCount++ },
		"parsed document": func(a *SchemaWikiCitationPreviewAuthorityV1) {
			a.Request.ParsedDocumentSHA256 = strings.Repeat("a", 64)
		},
		"field":            func(a *SchemaWikiCitationPreviewAuthorityV1) { a.FieldID = "foreign" },
		"chunk":            func(a *SchemaWikiCitationPreviewAuthorityV1) { a.ChunkID = "foreign" },
		"locator":          func(a *SchemaWikiCitationPreviewAuthorityV1) { a.LocatorRef = "foreign" },
		"page":             func(a *SchemaWikiCitationPreviewAuthorityV1) { a.PageNumber++ },
		"bbox":             func(a *SchemaWikiCitationPreviewAuthorityV1) { a.BBox.X0++ },
		"coordinate space": func(a *SchemaWikiCitationPreviewAuthorityV1) { a.CoordinateSpaceVersion = "mineru-0-1000-top-left.v1" },
		"page width":       func(a *SchemaWikiCitationPreviewAuthorityV1) { a.PageWidth++ },
		"page height":      func(a *SchemaWikiCitationPreviewAuthorityV1) { a.PageHeight++ },
		"rotation":         func(a *SchemaWikiCitationPreviewAuthorityV1) { a.RotationDegrees = 90 },
		"quote":            func(a *SchemaWikiCitationPreviewAuthorityV1) { a.QuoteSHA256 = strings.Repeat("a", 64) },
		"content":          func(a *SchemaWikiCitationPreviewAuthorityV1) { a.ContentSnapshotSHA256 = strings.Repeat("a", 64) },
		"evidence receipt": func(a *SchemaWikiCitationPreviewAuthorityV1) { a.EvidenceReceiptSHA256s[0] = strings.Repeat("a", 64) },
		"token":            func(a *SchemaWikiCitationPreviewAuthorityV1) { a.OpaqueToken = "https://current.invalid/file.pdf" },
	}
	for name, mutate := range tests {
		name, mutate := name, mutate
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			fixture := newSchemaWikiCitationRevisionFixture(t)
			fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
			blob := []byte("%PDF-1.7\nimmutable attempt 119\n%%EOF")
			authority := schemaWikiCitationPreviewAuthorityForFixture(t, fixture, blob)
			originalRequest := authority.Request
			mutate(authority)
			authority.AuthoritySHA256 = schemaWikiCitationPreviewAuthoritySHA256(*authority)
			reader := &schemaWikiImmutableRevisionSnapshotReaderStub{authority: authority, blob: blob}
			adapter := newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks, reader)
			ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(10003))

			validationErr := validateSchemaWikiCitationPreviewAuthority(originalRequest, *authority)
			require.ErrorIs(t, validationErr, ErrSchemaWikiCitationUnavailable)
			opened, err := adapter.ReadExactRevision(ctx, fixture.request)
			require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
			require.Empty(t, opened)
			require.Equal(t, 1, reader.resolveCalls)
			require.Zero(t, reader.fetchCalls)
		})
	}
}

func TestSchemaWikiCitationRevisionAdapterRejectsRehashedCandidateCoordinateReceiptBeforeSnapshot(t *testing.T) {
	t.Parallel()
	tests := map[string]func(*SchemaWikiCitationCoordinateAuthorityReceiptV1){
		"candidate":        func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) { r.CandidateSHA256 = strings.Repeat("a", 64) },
		"evidence attempt": func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) { r.EvidenceParseAttemptID = "attempt-120" },
		"weknora attempt":  func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) { r.WeKnoraParseAttempt++ },
		"file sha":         func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) { r.FileSHA256 = strings.Repeat("a", 64) },
		"parsed document": func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) {
			r.ParsedDocumentSHA256 = strings.Repeat("a", 64)
		},
		"parsed manifest": func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) {
			r.ParseManifestSHA256 = strings.Repeat("a", 64)
		},
		"weknora manifest": func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) {
			r.WeKnoraManifestDigest = strings.Repeat("a", 64)
		},
		"coordinate policy": func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) {
			r.CoordinatePolicySHA256 = strings.Repeat("a", 64)
		},
		"source coordinate": func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) { r.SourceCoordinateSpace = "normalized_0_1e6" },
		"bbox preimage":     func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) { r.SourceBBoxPreimage[0] = "101" },
		"page derivation":   func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) { r.NativePageIndex++ },
		"chunk content": func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) {
			r.ChunkContentSHA256 = strings.Repeat("a", 64)
		},
		"quote occurrence": func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) { r.QuoteOccurrenceCount = 2 },
		"cell exact claim": func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) {
			r.LocatorKind = "cell"
			r.HighlightPrecision = "locator_exact"
		},
		"live source receipt": func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) {
			r.LiveRevisionSourceReceiptSHA256 = strings.Repeat("a", 64)
		},
		"live source preimage": func(r *SchemaWikiCitationCoordinateAuthorityReceiptV1) {
			r.LiveRevisionSourceReceipt.PageCount++
		},
	}
	for name, mutate := range tests {
		name, mutate := name, mutate
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			fixture := newSchemaWikiCitationRevisionFixture(t)
			fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
			receipt := *fixture.request.CoordinateAuthorityReceipt
			mutate(&receipt)
			receipt.ReceiptSHA256 = schemaWikiCitationCoordinateAuthorityReceiptSHA256(receipt)
			fixture.request.CoordinateAuthorityReceipt = &receipt
			authority := schemaWikiCitationPreviewAuthorityForFixture(
				t, fixture, []byte("%PDF-1.7\nfixed\n%%EOF"),
			)
			reader := &schemaWikiImmutableRevisionSnapshotReaderStub{authority: authority}
			adapter := newSchemaWikiCitationRevisionReadAdapter(
				fixture.revisions, fixture.chunks, reader,
			)
			ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(10003))

			opened, err := adapter.ReadExactRevision(ctx, fixture.request)
			require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
			require.Empty(t, opened)
			require.Zero(t, reader.resolveCalls)
			require.Zero(t, reader.fetchCalls)
		})
	}
}

func TestSchemaWikiCitationRevisionAdapterRejectsRehashedC6NativeIdentityDrift(t *testing.T) {
	t.Parallel()
	tests := map[string]func(*testing.T, *schemaWikiCitationRevisionFixture){
		"missing native attempt": func(t *testing.T, fixture *schemaWikiCitationRevisionFixture) {
			receipt := fixture.request.CoordinateAuthorityReceipt
			receipt.WeKnoraParseAttempt = 0
			receipt.LiveRevisionSourceReceipt.WeKnoraParseAttempt = 0
			liveDigest, err := types.ComputeLiveRevisionSourceReceiptSHA256(
				receipt.LiveRevisionSourceReceipt,
			)
			require.Error(t, err)
			receipt.LiveRevisionSourceReceipt.SourceReceiptSHA256 = liveDigest
			receipt.LiveRevisionSourceReceiptSHA256 = liveDigest
			receipt.ReceiptSHA256 = schemaWikiCitationCoordinateAuthorityReceiptSHA256(*receipt)
			rebindSchemaWikiCitationFixtureToReceipt(t, fixture)
		},
		"evidence attempt mismatch": func(t *testing.T, fixture *schemaWikiCitationRevisionFixture) {
			receipt := fixture.request.CoordinateAuthorityReceipt
			receipt.EvidenceParseAttemptID = "different-evidence-attempt"
			receipt.LiveRevisionSourceReceipt.EvidenceParseAttemptID = receipt.EvidenceParseAttemptID
			liveDigest, err := types.ComputeLiveRevisionSourceReceiptSHA256(
				receipt.LiveRevisionSourceReceipt,
			)
			require.NoError(t, err)
			receipt.LiveRevisionSourceReceipt.SourceReceiptSHA256 = liveDigest
			receipt.LiveRevisionSourceReceiptSHA256 = liveDigest
			receipt.ReceiptSHA256 = schemaWikiCitationCoordinateAuthorityReceiptSHA256(*receipt)
			rebindSchemaWikiCitationFixtureToReceipt(t, fixture)
		},
		"revision source mismatch": func(t *testing.T, fixture *schemaWikiCitationRevisionFixture) {
			fixture.request.Citation.SourceRevisionID = "foreign-revision-source"
			fixture.request.Citation.CitationSHA256 = ""
			fixture.request.Citation.CitationSHA256 = schemaWikiTestHashWithout(
				t, fixture.request.Citation.Contract, fixture.request.Citation, "citation_sha256",
			)
			fixture.request.Binding.CitationSHA256 = fixture.request.Citation.CitationSHA256
			fixture.request.Binding.BindingSHA256 = ""
			fixture.request.Binding.BindingSHA256 = schemaWikiTestHashWithout(
				t, fixture.request.Binding.Contract, fixture.request.Binding, "binding_sha256",
			)
		},
		"joined field mismatch": func(t *testing.T, fixture *schemaWikiCitationRevisionFixture) {
			receipt := fixture.request.CoordinateAuthorityReceipt
			receipt.FieldID = "foreign-field"
			receipt.ReceiptSHA256 = schemaWikiCitationCoordinateAuthorityReceiptSHA256(*receipt)
			rebindSchemaWikiCitationFixtureToReceipt(t, fixture)
		},
	}
	for name, mutate := range tests {
		name, mutate := name, mutate
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			fixture := newSchemaWikiCitationRevisionFixture(t)
			bindSchemaWikiCitationFixtureToC6NativeIdentity(
				t, &fixture, "c3-evidence-parse-identity", 2,
			)
			fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
			mutate(t, &fixture)
			adapter := newSchemaWikiCitationRevisionReadAdapter(
				fixture.revisions, fixture.chunks,
			)
			ctx := context.WithValue(
				context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID,
			)

			_, err := adapter.resolveExactRevisionAuthority(ctx, fixture.request)
			require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
			require.Zero(t, fixture.revisions.knowledgeCalls)
			require.Zero(t, fixture.revisions.revisionCalls)
		})
	}
}

func TestSchemaWikiCitationRevisionAdapterRejectsPageOutsidePinnedSource(t *testing.T) {
	t.Parallel()
	fixture := newSchemaWikiCitationRevisionFixture(t)
	fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
	ratePageCount := 2
	fixture.revisions.source.PageCount = &ratePageCount
	reader := &schemaWikiImmutableRevisionSnapshotReaderStub{}
	adapter := newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks, reader)
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(10003))

	opened, err := adapter.ReadExactRevision(ctx, fixture.request)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
	require.Empty(t, opened)
	require.Zero(t, reader.resolveCalls)
	require.Zero(t, reader.fetchCalls)
}

func TestSchemaWikiCitationRevisionAdapterReplaysNativeAuthorityButDoesNotClaimCurrentBlob(t *testing.T) {
	t.Parallel()
	fixture := newSchemaWikiCitationRevisionFixture(t)
	fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
	adapter := NewSchemaWikiCitationRevisionReadAdapter(
		&schemaWikiProductionKnowledgeRepositoryStub{delegate: fixture.revisions},
		&schemaWikiProductionChunkRepositoryStub{delegate: fixture.chunks},
	)
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(10003))
	resolved, resolveErr := adapter.resolveExactRevisionAuthority(ctx, fixture.request)
	require.NoError(t, resolveErr)
	require.NotNil(t, resolved)
	require.Equal(t, fixture.request.CoordinateAuthorityReceipt.ReceiptSHA256, resolved.OpaqueToken)
	require.Equal(t, fixture.request.CoordinateAuthorityReceipt.NormalizedBBox, resolved.BBox)
	fixture.revisions.knowledgeCalls = 0
	fixture.revisions.revisionCalls = 0
	fixture.chunks.getCalls = 0
	fixture.chunks.listCalls = 0

	opened, err := adapter.ReadExactRevision(ctx, fixture.request)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
	require.Empty(t, opened)
	require.Equal(t, 1, fixture.revisions.knowledgeCalls)
	require.Equal(t, 1, fixture.revisions.revisionCalls)
	require.Equal(t, 1, fixture.chunks.getCalls)
	require.Equal(t, 1, fixture.chunks.listCalls)
}

func TestSchemaWikiCitationRevisionAdapterRejectsAuthorityDriftWithoutFallback(t *testing.T) {
	t.Parallel()
	tests := map[string]func(*schemaWikiCitationRevisionFixture){
		"space": func(f *schemaWikiCitationRevisionFixture) {
			f.request.Scope.SpaceID = "foreign-space"
		},
		"raw knowledge base": func(f *schemaWikiCitationRevisionFixture) {
			f.revisions.knowledge.KnowledgeBaseID = "foreign-raw"
		},
		"source revision": func(f *schemaWikiCitationRevisionFixture) {
			f.request.Citation.SourceRevisionID = "revision-120"
		},
		"parse attempt": func(f *schemaWikiCitationRevisionFixture) {
			f.request.Citation.ParseAttemptID = "attempt-120"
		},
		"document digest": func(f *schemaWikiCitationRevisionFixture) {
			f.revisions.revision.FileSHA256 = strings.Repeat("c", 64)
		},
		"manifest digest": func(f *schemaWikiCitationRevisionFixture) {
			f.revisions.revision.ManifestDigest = strings.Repeat("c", 64)
		},
		"chunk knowledge": func(f *schemaWikiCitationRevisionFixture) {
			f.chunks.chunk.KnowledgeID = "foreign-knowledge"
		},
		"chunk attempt": func(f *schemaWikiCitationRevisionFixture) {
			f.chunks.chunk.ParseAttempt = 120
		},
		"chunk content": func(f *schemaWikiCitationRevisionFixture) {
			f.chunks.chunk.Content = "drifted chunk content"
		},
		"quote replay": func(f *schemaWikiCitationRevisionFixture) {
			f.chunks.chunk.Content = "unrelated text"
		},
		"missing page": func(f *schemaWikiCitationRevisionFixture) {
			f.request.Citation.PageNumber = 0
		},
		"missing bbox": func(f *schemaWikiCitationRevisionFixture) {
			f.request.Citation.BBox.X1 = f.request.Citation.BBox.X0
		},
		"non pdf": func(f *schemaWikiCitationRevisionFixture) {
			f.revisions.knowledge.FileType = "md"
		},
	}
	for name, mutate := range tests {
		name, mutate := name, mutate
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			fixture := newSchemaWikiCitationRevisionFixture(t)
			fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
			mutate(&fixture)
			adapter := newSchemaWikiCitationRevisionReadAdapter(
				fixture.revisions, fixture.chunks,
			)
			ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(10003))
			opened, err := adapter.ReadExactRevision(ctx, fixture.request)
			require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
			require.Empty(t, opened)
		})
	}
}

func TestSchemaWikiCitationRevisionAdapterRejectsMissingTenantBeforeRepositories(t *testing.T) {
	t.Parallel()
	fixture := newSchemaWikiCitationRevisionFixture(t)
	fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
	adapter := newSchemaWikiCitationRevisionReadAdapter(
		fixture.revisions, fixture.chunks,
	)

	opened, err := adapter.ReadExactRevision(context.Background(), fixture.request)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
	require.Empty(t, opened)
	require.Zero(t, fixture.revisions.knowledgeCalls)
}
