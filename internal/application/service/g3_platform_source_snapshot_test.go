package service

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type g3PlatformSourceAuthorizerStub struct {
	err   error
	calls int
}

func (s *g3PlatformSourceAuthorizerStub) AuthorizeG3PlatformSourceSnapshot(
	_ context.Context, _ types.WikiReleaseScope, _ string, _ int64,
) error {
	s.calls++
	return s.err
}

type g3PlatformSnapshotSignerStub struct {
	err       error
	calls     int
	domain    string
	digest    string
	keyID     string
	signature []byte
}

func (s *g3PlatformSnapshotSignerStub) SignG3PlatformSnapshot(
	_ context.Context, domain string, digest string,
) (string, []byte, error) {
	s.calls++
	s.domain, s.digest = domain, digest
	return s.keyID, append([]byte(nil), s.signature...), s.err
}

type g3PlatformSourceEnsurerStub struct {
	source *types.KnowledgeRevisionSource
	err    error
	calls  int
}

type g3PlatformProcessingReceiptStub struct {
	receipt G3PlatformSourceProcessingReceiptV1
	err     error
	calls   int
}

func (s *g3PlatformProcessingReceiptStub) ProcessingReceipt(
	_ context.Context, _ types.WikiReleaseScope, _ string, _ int64,
) (G3PlatformSourceProcessingReceiptV1, error) {
	s.calls++
	return s.receipt, s.err
}

func g3PlatformLegacyProcessingReceipt(t *testing.T, knowledgeID string, parseAttempt int64) G3PlatformSourceProcessingReceiptV1 {
	t.Helper()
	receipt := G3PlatformSourceProcessingReceiptV1{
		Contract:             G3PlatformProcessingReceiptContractV1,
		Availability:         G3PlatformProcessingUnavailable,
		KnowledgeID:          knowledgeID,
		ParseAttempt:         parseAttempt,
		UnavailabilityReason: "LEGACY_NO_JOURNAL",
		Phases:               modelDispatchPhases(nil),
	}
	var err error
	receipt.ReceiptSHA256, err = modelDispatchDigest(receipt.Contract, receipt)
	require.NoError(t, err)
	return receipt
}

func g3PlatformAvailableProcessingReceipt(t *testing.T, knowledgeID string, parseAttempt int64) G3PlatformSourceProcessingReceiptV1 {
	t.Helper()
	calls := []G3PlatformProcessingCallReceiptV1{}
	receipt := G3PlatformSourceProcessingReceiptV1{
		Contract:            G3PlatformProcessingReceiptContractV1,
		Availability:        G3PlatformProcessingAvailable,
		KnowledgeID:         knowledgeID,
		ParseAttempt:        parseAttempt,
		ProcessingAttempt:   4,
		JournalMarkerSHA256: strings.Repeat("1", 64),
		Calls:               &calls,
		Counts:              &G3PlatformProcessingCountsV1{},
		Phases:              modelDispatchPhases(nil),
	}
	var err error
	receipt.ReceiptSHA256, err = modelDispatchDigest(receipt.Contract, receipt)
	require.NoError(t, err)
	return receipt
}

func (s *g3PlatformSourceEnsurerStub) ensureCurrentCompletedForScope(
	_ context.Context, _ types.WikiReleaseScope, _ string, _ int64,
) (*types.KnowledgeRevisionSource, error) {
	s.calls++
	return s.source, s.err
}

func TestG3PlatformSourceSnapshotCapturesOnceAndSignsCanonicalPayload(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	authority, doc, scope, _, _ := nativeIndexFixture830G2(t)
	authority.codec = sourceReuseTestCodec830G3(t)
	authority.sourceReuse = newConceptSourceReuseStore830G3(authority.codec)
	readySourceReuseResource830G3(authority)
	repository := authority.revisions.(*conceptKnowledgeStub830G2)
	ensurer := &g3PlatformSourceEnsurerStub{source: repository.source}
	authorizer := &g3PlatformSourceAuthorizerStub{}
	signer := &g3PlatformSnapshotSignerStub{keyID: "source-key-1", signature: []byte("signed-source")}
	processing := &g3PlatformProcessingReceiptStub{receipt: g3PlatformAvailableProcessingReceipt(t, "knowledge-1", 1)}
	service := NewG3PlatformSourceSnapshotService(ensurer, authority, processing, authorizer, signer)

	first, err := service.Capture(context.Background(), scope, "knowledge-1", 1)
	require.NoError(t, err)
	second, err := service.Capture(context.Background(), scope, "knowledge-1", 1)
	require.NoError(t, err)

	require.Equal(t, first.Snapshot, second.Snapshot)
	require.Equal(t, G3PlatformSourceSnapshotContractV1, first.Snapshot.Contract)
	require.Equal(t, repository.source.BindingDigest, first.Snapshot.Receipt.BindingDigest)
	require.Equal(t, repository.source.ManifestDigest, first.Snapshot.Receipt.ManifestDigest)
	require.Equal(t, processing.receipt, first.Snapshot.ProcessingReceipt)
	require.Equal(t, first.Snapshot.SnapshotSHA256, first.Authority.PayloadSHA256)
	require.Equal(t, G3PlatformSourceSnapshotSigningDomainV1, first.Authority.Domain)
	require.Equal(t, "source-key-1", first.Authority.KeyID)
	require.Equal(t, []byte("signed-source"), first.Authority.Signature)
	require.Len(t, first.Snapshot.Chunks, 1)
	require.Equal(t, "chunk-1", first.Snapshot.Chunks[0].ID)
	require.Equal(t, "prefix A😀 suffix", first.Snapshot.Chunks[0].Content)
	require.Equal(t, G3PlatformChunkMappingUnresolved, first.Snapshot.ChunkPageMappings[0].Status)
	require.Nil(t, first.Snapshot.ChunkPageMappings[0].SourcePageNumber)
	require.Empty(t, first.Snapshot.ChunkPageMappings[0].PageSpans)
	require.Equal(t, 1, doc.calls, "the fixed source capture must survive repeat calls")
	require.Equal(t, 2, ensurer.calls, "every read must recheck the current fixed binding")
	require.Equal(t, 2, authorizer.calls)
	require.Equal(t, 2, signer.calls)
	require.Equal(t, 2, processing.calls)
}

func TestG3PlatformSourceSnapshotMapsUniqueCrossPageChunkWithoutChangingIt(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	authority, _, scope, _, _ := nativeIndexFixture830G2(t)
	authority.codec = sourceReuseTestCodec830G3(t)
	authority.sourceReuse = newConceptSourceReuseStore830G3(authority.codec)
	readySourceReuseResource830G3(authority)
	repository := authority.revisions.(*conceptKnowledgeStub830G2)
	chunk := authority.chunks.(conceptChunksStub830G2).chunks[0]
	chunk.Content = "A😀\n\n\u4e2d"
	manifest, err := types.ComputeRevisionManifestDigest(repository.source.KnowledgeID,
		repository.source.ParseAttempt, []types.RevisionManifestChunk{{ID: chunk.ID, Index: chunk.ChunkIndex, Content: chunk.Content}})
	require.NoError(t, err)
	repository.revision.ManifestDigest = manifest
	repository.source.ManifestDigest = manifest
	repository.source.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(*repository.source)
	require.NoError(t, err)
	authority.chunks = conceptChunksStub830G2{chunks: []*types.Chunk{chunk}}

	service := NewG3PlatformSourceSnapshotService(
		&g3PlatformSourceEnsurerStub{source: repository.source}, authority,
		&g3PlatformProcessingReceiptStub{receipt: g3PlatformLegacyProcessingReceipt(t, "knowledge-1", 1)},
		&g3PlatformSourceAuthorizerStub{},
		&g3PlatformSnapshotSignerStub{keyID: "source-key-1", signature: []byte("signed-source")},
	)
	result, err := service.Capture(context.Background(), scope, "knowledge-1", 1)
	require.NoError(t, err)
	require.Equal(t, chunk.Content, result.Snapshot.Chunks[0].Content)
	mapping := result.Snapshot.ChunkPageMappings[0]
	require.Equal(t, G3PlatformChunkMappingExactBlock, mapping.Status)
	require.NotNil(t, mapping.SourcePageNumber)
	require.Equal(t, 1, *mapping.SourcePageNumber)
	require.Len(t, mapping.PageSpans, 2)
	require.NotNil(t, mapping.BlockGlobalStart)
	require.NotNil(t, mapping.BlockGlobalEnd)
	require.Equal(t, len([]rune(chunk.Content)), *mapping.BlockGlobalEnd-*mapping.BlockGlobalStart)
}

func TestG3PlatformSourceSnapshotFailsClosedBeforeSourceReads(t *testing.T) {
	scope := types.WikiReleaseScope{TenantID: 1, SpaceID: "space-1", RawKBID: "raw-1", WikiKBID: "wiki-1"}
	ensurer := &g3PlatformSourceEnsurerStub{}
	authorizer := &g3PlatformSourceAuthorizerStub{err: errors.New("denied")}
	signer := &g3PlatformSnapshotSignerStub{keyID: "source-key-1", signature: []byte("signed-source")}
	processing := &g3PlatformProcessingReceiptStub{receipt: g3PlatformLegacyProcessingReceipt(t, "knowledge-1", 1)}
	service := NewG3PlatformSourceSnapshotService(ensurer, &ConceptSourceAuthorityService830G2{}, processing, authorizer, signer)
	_, err := service.Capture(context.Background(), scope, "knowledge-1", 1)
	require.ErrorIs(t, err, ErrG3PlatformSnapshotUnauthorized)
	require.Zero(t, ensurer.calls)
	require.Zero(t, signer.calls)

	service = NewG3PlatformSourceSnapshotService(ensurer, &ConceptSourceAuthorityService830G2{}, processing, nil, signer)
	_, err = service.Capture(context.Background(), scope, "knowledge-1", 1)
	require.ErrorIs(t, err, ErrG3PlatformSnapshotUnavailable)
	require.Zero(t, ensurer.calls)

	service = NewG3PlatformSourceSnapshotService(ensurer, &ConceptSourceAuthorityService830G2{}, processing, &g3PlatformSourceAuthorizerStub{}, nil)
	_, err = service.Capture(context.Background(), scope, "knowledge-1", 1)
	require.ErrorIs(t, err, ErrG3PlatformSnapshotUnavailable)
	require.Zero(t, ensurer.calls)

	service = NewG3PlatformSourceSnapshotService(ensurer, &ConceptSourceAuthorityService830G2{}, nil, &g3PlatformSourceAuthorizerStub{}, signer)
	_, err = service.Capture(context.Background(), scope, "knowledge-1", 1)
	require.ErrorIs(t, err, ErrG3PlatformSnapshotUnavailable)
	require.Zero(t, ensurer.calls)
}

func TestKnowledgeRevisionSourceSystemEnsureUsesExactScopeAndAttempt(t *testing.T) {
	service, repository, _ := revisionSourceFixture(t)
	scope := types.WikiReleaseScope{TenantID: 10003, SpaceID: "space-1", RawKBID: "raw-kb-1", WikiKBID: "wiki-1"}
	sealed, err := service.ensureCurrentCompletedForScope(context.Background(), scope, "knowledge-1", 2)
	require.NoError(t, err)
	require.NoError(t, types.ValidateKnowledgeRevisionSourceBinding(*sealed))
	require.Equal(t, 1, repository.sealCalls)

	foreign := *sealed
	foreign.KnowledgeID = "foreign-knowledge"
	foreign.RevisionSourceID, err = types.ComputeKnowledgeRevisionSourceID(foreign)
	require.NoError(t, err)
	foreign.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(foreign)
	require.NoError(t, err)
	repository.source, repository.sourceErr = &foreign, nil
	reopened, err := service.ensureCurrentCompletedForScope(context.Background(), scope, "knowledge-1", 2)
	require.NoError(t, err)
	require.Equal(t, "knowledge-1", reopened.KnowledgeID)
	require.Equal(t, 2, repository.sealCalls, "a foreign exact-read row must not be accepted as the requested source")

	wrong := scope
	wrong.RawKBID = "other-raw"
	_, err = service.ensureCurrentCompletedForScope(context.Background(), wrong, "knowledge-1", 2)
	require.ErrorIs(t, err, ErrRevisionSourceMismatch)
	_, err = service.ensureCurrentCompletedForScope(context.Background(), scope, "knowledge-1", 3)
	require.ErrorIs(t, err, ErrRevisionSourceMismatch)
}
