package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
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
	release := loadSchemaWikiReleaseVector(t)
	citation := firstSchemaWikiCitation(t, release)
	content := "prefix " + citation.QuoteSnapshot + " suffix"
	contentDigest := sha256.Sum256([]byte(content))
	manifestChunks := []types.RevisionManifestChunk{{
		ID: citation.ChunkID, Index: 0, Content: content,
	}}
	manifestDigest, err := types.ComputeRevisionManifestDigest(citation.KnowledgeID, 119, manifestChunks)
	require.NoError(t, err)
	// The sealed ParsedDocument is bound to the same file identity as the
	// native revision. The read still cannot open an immutable attempt-bound
	// blob: the production preview API serves only the current file.
	citation.ParsedDocumentSHA256 = strings.Repeat("e", 64)
	citation.ParseManifestSHA256 = manifestDigest
	citation.ContentSnapshotSHA256 = hex.EncodeToString(contentDigest[:])
	citation.SourceRevisionID = "revision-119"
	citation.ParseAttemptID = "attempt-119"
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
	return schemaWikiCitationRevisionFixture{
		request: CitationRevisionReadRequestV1{
			Scope: scope, Citation: citation, Binding: binding,
		},
		revisions: &schemaWikiCitationRevisionRepositoryStub{
			knowledge: &types.Knowledge{
				ID: citation.KnowledgeID, TenantID: scope.TenantID,
				KnowledgeBaseID: scope.RawKBID, ParseStatus: types.ParseStatusCompleted,
				CurrentParseAttempt: 119, FileType: "pdf",
				FileSHA256: strings.Repeat("e", 64),
			},
			revision: &types.KnowledgeRevision{
				KnowledgeID: citation.KnowledgeID, ParseAttempt: 119,
				FileSHA256:        strings.Repeat("e", 64),
				ManifestAlgorithm: types.RevisionManifestAlgorithm,
				ManifestDigest:    citation.ParseManifestSHA256, ChunkCount: 1,
			},
		},
		chunks: &schemaWikiCitationChunkRepositoryStub{chunk: &types.Chunk{
			ID: citation.ChunkID, TenantID: scope.TenantID,
			KnowledgeID: citation.KnowledgeID, KnowledgeBaseID: scope.RawKBID,
			ParseAttempt: 119, ChunkType: types.ChunkTypeText,
			Content: content, ChunkIndex: 0, StartAt: 0, EndAt: len(content),
		}},
	}
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
