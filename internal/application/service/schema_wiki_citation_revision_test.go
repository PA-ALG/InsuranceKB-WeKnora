package service

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

type schemaWikiCitationRevisionRepositoryStub struct {
	knowledge      *types.Knowledge
	revision       *types.KnowledgeRevision
	source         *types.KnowledgeRevisionSource
	resource       *types.StoredResource
	knowledgeCalls int
	revisionCalls  int
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
	if s.revision == nil || s.revision.KnowledgeID != knowledgeID || s.revision.ParseAttempt != attempt {
		return nil, errors.New("revision unavailable")
	}
	copy := *s.revision
	return &copy, nil
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
		ParseAttempt:         119,
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
