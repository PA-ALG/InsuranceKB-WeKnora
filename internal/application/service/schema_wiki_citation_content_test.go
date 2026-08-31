package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type schemaWikiRevisionBlobReaderSpy struct {
	bytes []byte
	calls int
}

func (s *schemaWikiRevisionBlobReaderSpy) ReadExactRevisionSource(
	_ context.Context,
	_ types.LiveRevisionSourceReceiptV1,
) ([]byte, error) {
	s.calls++
	return append([]byte(nil), s.bytes...), nil
}

func bindSchemaWikiCitationFixtureToBlob(
	t *testing.T,
	fixture *schemaWikiCitationRevisionFixture,
	blob []byte,
) {
	t.Helper()
	sum := sha256.Sum256(blob)
	digest := hex.EncodeToString(sum[:])
	fixture.revisions.revision.FileSHA256 = digest
	fixture.revisions.source.FileSHA256 = digest
	fixture.revisions.resource.ContentHash = digest
	sourceID, err := types.ComputeKnowledgeRevisionSourceID(*fixture.revisions.source)
	require.NoError(t, err)
	fixture.revisions.source.RevisionSourceID = sourceID
	receipt := fixture.request.CoordinateAuthorityReceipt
	receipt.SourceSHA256 = digest
	receipt.FileSHA256 = digest
	receipt.LiveRevisionSourceReceipt.RevisionSourceID = sourceID
	receipt.LiveRevisionSourceReceipt.FileSHA256 = digest
	liveDigest, err := types.ComputeLiveRevisionSourceReceiptSHA256(receipt.LiveRevisionSourceReceipt)
	require.NoError(t, err)
	receipt.LiveRevisionSourceReceipt.SourceReceiptSHA256 = liveDigest
	receipt.LiveRevisionSourceReceiptSHA256 = liveDigest
	receipt.ReceiptSHA256 = schemaWikiCitationCoordinateAuthorityReceiptSHA256(*receipt)
}

func TestSchemaWikiCitationContentIssuesBoundAuthorityThenFetchesByTokenOnly(t *testing.T) {
	t.Parallel()
	now := time.Unix(1786441800, 0).UTC()
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x75}, ed25519.SeedSize))
	codec, err := NewSchemaWikiCitationTokenCodec(
		"citation-token-key-1",
		map[string]ed25519.PrivateKey{"citation-token-key-1": privateKey},
		func() time.Time { return now },
	)
	require.NoError(t, err)

	pdf := []byte("%PDF-1.7\nfixed immutable source\n%%EOF")
	fixture := newSchemaWikiCitationRevisionFixture(t)
	bindSchemaWikiCitationFixtureToBlob(t, &fixture, pdf)
	fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
	snapshot := &schemaWikiImmutableRevisionSnapshotReaderStub{
		authority: schemaWikiCitationPreviewAuthorityForFixture(t, fixture, pdf),
	}
	blob := &schemaWikiRevisionBlobReaderSpy{bytes: pdf}
	content := newSchemaWikiCitationContentService(
		newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks, snapshot),
		blob,
		codec,
	)
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(10003))
	authority, err := content.IssueExactRevision(ctx, fixture.request)
	require.NoError(t, err)
	require.Equal(t, "citation-token-key-1", authority.TokenKeyID)
	require.Equal(t, fixture.request.ReleaseID, authority.ReleaseID)
	require.Equal(t, fixture.request.ActivationEpoch, authority.ActivationEpoch)
	require.Equal(t, fixture.request.FieldID, authority.FieldID)
	require.Equal(t, fixture.request.Citation.CitationID, authority.CitationID)
	require.Equal(t, fixture.revisions.source.RevisionSourceID, authority.RevisionSource.RevisionSourceID)
	require.Equal(t, fixture.revisions.revision.FileSHA256, authority.RevisionSource.FileSHA256)
	require.Equal(t, fixture.request.Citation.PageNumber, authority.PageNumber)
	require.NotEmpty(t, authority.OpaqueToken)
	parts := strings.Split(authority.OpaqueToken, ".")
	require.Len(t, parts, 3)
	tokenPayload, decodeErr := base64.RawURLEncoding.DecodeString(parts[1])
	require.NoError(t, decodeErr)
	require.NotContains(t, string(tokenPayload), fixture.request.Citation.QuoteSnapshot)
	require.NotContains(t, string(tokenPayload), "quote_snapshot")
	require.Zero(t, blob.calls, "authority issuance must not open PDF bytes")

	resolved, err := content.ResolveOpaqueToken(ctx, fixture.request.Scope, authority.OpaqueToken)
	require.NoError(t, err)
	require.Equal(t, authority.AuthoritySHA256, resolved.AuthoritySHA256)
	opened, err := content.ReadByOpaqueToken(
		ctx, fixture.request.Scope, authority.OpaqueToken, fixture.request,
	)
	require.NoError(t, err)
	require.Equal(t, pdf, opened)
	require.Equal(t, 1, blob.calls)
}

func TestSchemaWikiCitationContentReplaysC6EvidenceIdentityThroughNativeParseAttempt(t *testing.T) {
	t.Parallel()
	now := time.Unix(1786441800, 0).UTC()
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x78}, ed25519.SeedSize))
	codec, err := NewSchemaWikiCitationTokenCodec(
		"citation-token-key-c6-native",
		map[string]ed25519.PrivateKey{"citation-token-key-c6-native": privateKey},
		func() time.Time { return now },
	)
	require.NoError(t, err)

	pdf := []byte("%PDF-1.7\nfixed C6 native revision\n%%EOF")
	fixture := newSchemaWikiCitationRevisionFixture(t)
	bindSchemaWikiCitationFixtureToBlob(t, &fixture, pdf)
	bindSchemaWikiCitationFixtureToC6NativeIdentity(
		t, &fixture, "c3-evidence-parse-identity", 2,
	)
	fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
	snapshot := &schemaWikiImmutableRevisionSnapshotReaderStub{
		authority: schemaWikiCitationPreviewAuthorityForFixture(t, fixture, pdf),
	}
	blob := &schemaWikiRevisionBlobReaderSpy{bytes: pdf}
	content := newSchemaWikiCitationContentService(
		newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks, snapshot),
		blob,
		codec,
	)
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(10003))

	authority, err := content.IssueExactRevision(ctx, fixture.request)
	require.NoErrorf(t, err,
		"knowledge=%d revision=%d attempt=%d chunks=%d/%d snapshot=%d",
		fixture.revisions.knowledgeCalls, fixture.revisions.revisionCalls,
		fixture.revisions.lastAttempt, fixture.chunks.getCalls, fixture.chunks.listCalls,
		snapshot.resolveCalls,
	)
	require.Equal(t, int64(2), fixture.revisions.lastAttempt)
	require.Equal(t,
		fixture.request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt,
		authority.RevisionSource,
	)
	opened, err := content.ReadByOpaqueToken(
		ctx, fixture.request.Scope, authority.OpaqueToken, fixture.request,
	)
	require.NoError(t, err)
	require.Equal(t, pdf, opened)
	require.Equal(t, 1, blob.calls)
}

func TestSchemaWikiCitationContentReadsFrozenC5SourceWithoutRewritingPublicAuthority(t *testing.T) {
	now := time.Unix(1786441800, 0).UTC()
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x79}, ed25519.SeedSize))
	codec, err := NewSchemaWikiCitationTokenCodec(
		"citation-token-key-c5-frozen",
		map[string]ed25519.PrivateKey{"citation-token-key-c5-frozen": privateKey},
		func() time.Time { return now },
	)
	require.NoError(t, err)
	fixture := newSchemaWikiCitationRevisionFixture(t)
	bindSchemaWikiCitationFixtureToFrozenC5ParentLineage(t, &fixture)
	publicReceipt := fixture.request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt
	blob := &schemaWikiRevisionBlobReaderSpy{bytes: []byte("must not be read")}
	content := newSchemaWikiCitationContentService(
		newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks), blob, codec,
	)
	ctx := context.WithValue(
		context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID,
	)
	authority, err := content.IssueExactRevision(ctx, fixture.request)
	require.NoError(t, err)
	require.Equal(t, publicReceipt, authority.RevisionSource)
	require.Zero(t, blob.calls)
	opened, err := content.ReadByOpaqueToken(
		ctx, fixture.request.Scope, authority.OpaqueToken, fixture.request,
	)
	require.NoError(t, err)
	require.Equal(t, fixture.request.frozenNativeSource.sourceBytes, opened)
	require.Zero(t, blob.calls, "exact15 source bytes replace no database custody")
}

func TestSchemaWikiCitationContentIssuesAndReadsFrozenC5OverlappingParentOccurrence(t *testing.T) {
	now := time.Unix(1786441800, 0).UTC()
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x7b}, ed25519.SeedSize))
	codec, err := NewSchemaWikiCitationTokenCodec(
		"citation-token-key-c5-overlap",
		map[string]ed25519.PrivateKey{"citation-token-key-c5-overlap": privateKey},
		func() time.Time { return now },
	)
	require.NoError(t, err)
	fixture := newSchemaWikiCitationRevisionFixture(t)
	_, _ = bindSchemaWikiCitationFixtureToFrozenC5OverlappingParentLineage(t, &fixture)
	publicReceipt := fixture.request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt
	blob := &schemaWikiRevisionBlobReaderSpy{bytes: []byte("must not be read")}
	content := newSchemaWikiCitationContentService(
		newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks), blob, codec,
	)
	ctx := context.WithValue(
		context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID,
	)

	authority, err := content.IssueExactRevision(ctx, fixture.request)
	require.NoError(t, err)
	require.Equal(t, publicReceipt, authority.RevisionSource)
	require.Zero(t, blob.calls)
	opened, err := content.ReadByOpaqueToken(
		ctx, fixture.request.Scope, authority.OpaqueToken, fixture.request,
	)
	require.NoError(t, err)
	require.Equal(t, fixture.request.frozenNativeSource.sourceBytes, opened)
	require.Zero(t, blob.calls)
}

func TestSchemaWikiCitationContentIssuesAndReadsFrozenC5UnicodeCodePointReceipt(t *testing.T) {
	now := time.Unix(1786441800, 0).UTC()
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x7a}, ed25519.SeedSize))
	codec, err := NewSchemaWikiCitationTokenCodec(
		"citation-token-key-c5-unicode",
		map[string]ed25519.PrivateKey{"citation-token-key-c5-unicode": privateKey},
		func() time.Time { return now },
	)
	require.NoError(t, err)
	fixture := newSchemaWikiCitationRevisionFixture(t)
	_, _, _, _ = bindSchemaWikiCitationFixtureToFrozenC5UnicodeQuote(t, &fixture)
	publicReceipt := fixture.request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt
	blob := &schemaWikiRevisionBlobReaderSpy{bytes: []byte("must not be read")}
	content := newSchemaWikiCitationContentService(
		newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks), blob, codec,
	)
	ctx := context.WithValue(
		context.Background(), types.TenantIDContextKey, fixture.request.Scope.TenantID,
	)
	authority, err := content.IssueExactRevision(ctx, fixture.request)
	require.NoError(t, err)
	require.Equal(t, publicReceipt, authority.RevisionSource)
	require.Zero(t, blob.calls)
	opened, err := content.ReadByOpaqueToken(
		ctx, fixture.request.Scope, authority.OpaqueToken, fixture.request,
	)
	require.NoError(t, err)
	require.Equal(t, fixture.request.frozenNativeSource.sourceBytes, opened)
	require.Zero(t, blob.calls)
}

func TestSchemaWikiGoldenEvidencePreviewUsesSeparatePreparationTokenClaims(t *testing.T) {
	t.Parallel()
	now := time.Unix(1786441800, 0).UTC()
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x77}, ed25519.SeedSize))
	codec, err := NewSchemaWikiCitationTokenCodec(
		"citation-token-key-golden",
		map[string]ed25519.PrivateKey{"citation-token-key-golden": privateKey},
		func() time.Time { return now },
	)
	require.NoError(t, err)
	pdf := []byte("%PDF-1.7\ngolden preparation immutable source\n%%EOF")
	fixture := newSchemaWikiCitationRevisionFixture(t)
	bindSchemaWikiCitationFixtureToBlob(t, &fixture, pdf)
	fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
	evidenceID := fixture.request.CoordinateAuthorityReceipt.ReceiptSHA256
	fixture.request.ReleaseID = ""
	fixture.request.ActivationEpoch = 0
	fixture.request.PreparationID = "preparation-596-1"
	fixture.request.EvaluationID = strings.Repeat("e", 64)
	fixture.request.EvidenceID = evidenceID
	snapshot := &schemaWikiImmutableRevisionSnapshotReaderStub{
		authority: schemaWikiCitationPreviewAuthorityForFixture(t, fixture, pdf),
	}
	blob := &schemaWikiRevisionBlobReaderSpy{bytes: pdf}
	content := newSchemaWikiCitationContentService(
		newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks, snapshot),
		blob,
		codec,
	)
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(10003))
	authority, err := content.IssuePreparationExactRevision(
		ctx,
		"preparation-596-1",
		strings.Repeat("e", 64),
		evidenceID,
		fixture.request,
	)
	require.NoError(t, err)
	require.Equal(t, "preparation-596-1", authority.PreparationID)
	require.Equal(t, evidenceID, authority.EvidenceID)
	require.NotEmpty(t, authority.OpaqueToken)
	parts := strings.Split(authority.OpaqueToken, ".")
	require.Len(t, parts, 3)
	payload, decodeErr := base64.RawURLEncoding.DecodeString(parts[1])
	require.NoError(t, decodeErr)
	require.NotContains(t, string(payload), fixture.request.Citation.QuoteSnapshot)
	require.NotContains(t, string(payload), "quote_snapshot")
	require.Zero(t, blob.calls)

	resolved, err := content.ResolvePreparationOpaqueToken(
		ctx, fixture.request.Scope, authority.OpaqueToken,
	)
	require.NoError(t, err)
	require.Equal(t, authority.AuthoritySHA256, resolved.AuthoritySHA256)
	opened, err := content.ReadPreparationByOpaqueToken(
		ctx,
		fixture.request.Scope,
		authority.OpaqueToken,
		"preparation-596-1",
		strings.Repeat("e", 64),
		evidenceID,
		fixture.request,
	)
	require.NoError(t, err)
	require.Equal(t, pdf, opened)
	require.Equal(t, 1, blob.calls)

	_, err = content.ResolveOpaqueToken(ctx, fixture.request.Scope, authority.OpaqueToken)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable,
		"preparation token must not be accepted as an Active-release token")
}

func TestSchemaWikiCitationContentRejectsDeleteGuardAndPageRangeBeforeBytes(t *testing.T) {
	t.Parallel()
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x76}, ed25519.SeedSize))
	codec, err := NewSchemaWikiCitationTokenCodec(
		"citation-token-key-2",
		map[string]ed25519.PrivateKey{"citation-token-key-2": privateKey},
		time.Now,
	)
	require.NoError(t, err)
	fixture := newSchemaWikiCitationRevisionFixture(t)
	fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
	pageCount := 2
	fixture.revisions.source.PageCount = &pageCount
	fixture.request.Citation.PageNumber = 12
	fixture.request.Citation.CitationSHA256 = schemaWikiTestHashWithout(
		t, fixture.request.Citation.Contract, fixture.request.Citation, "citation_sha256",
	)
	fixture.request.Binding.CitationSHA256 = fixture.request.Citation.CitationSHA256
	fixture.request.Binding.BindingSHA256 = schemaWikiTestHashWithout(
		t, fixture.request.Binding.Contract, fixture.request.Binding, "binding_sha256",
	)
	fixture.request.CoordinateAuthorityReceipt.NativePageIndex = 11
	fixture.request.CoordinateAuthorityReceipt.PageNumber = 12
	fixture.request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt.PageCount = pageCount
	liveDigest, liveErr := types.ComputeLiveRevisionSourceReceiptSHA256(
		fixture.request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt,
	)
	require.NoError(t, liveErr)
	fixture.request.CoordinateAuthorityReceipt.LiveRevisionSourceReceipt.SourceReceiptSHA256 = liveDigest
	fixture.request.CoordinateAuthorityReceipt.LiveRevisionSourceReceiptSHA256 = liveDigest
	fixture.request.CoordinateAuthorityReceipt.ReceiptSHA256 =
		schemaWikiCitationCoordinateAuthorityReceiptSHA256(*fixture.request.CoordinateAuthorityReceipt)
	blob := &schemaWikiRevisionBlobReaderSpy{bytes: []byte("%PDF-1.7\n%%EOF")}
	content := newSchemaWikiCitationContentService(
		newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks), blob, codec,
	)
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(10003))
	_, err = content.IssueExactRevision(ctx, fixture.request)
	require.ErrorIs(t, err, ErrSchemaWikiCitationPageUnavailable)
	require.Zero(t, blob.calls)

	fixture.revisions.source.RetentionState = types.KnowledgeRevisionSourceReleased
	_, err = content.ReadByOpaqueToken(
		ctx, fixture.request.Scope, "caller-cannot-supply-revision-or-page", fixture.request,
	)
	require.ErrorIs(t, err, ErrSchemaWikiCitationUnavailable)
	require.Zero(t, blob.calls)
}

func TestSchemaWikiCitationContentRouteAuthorityDerivesSignedTokenKindAndScope(t *testing.T) {
	t.Parallel()
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x77}, ed25519.SeedSize))
	codec, err := NewSchemaWikiCitationTokenCodec(
		"citation-token-key-route",
		map[string]ed25519.PrivateKey{"citation-token-key-route": privateKey},
		time.Now,
	)
	require.NoError(t, err)
	fixture := newSchemaWikiCitationRevisionFixture(t)
	fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
	content := newSchemaWikiCitationContentService(
		newSchemaWikiCitationRevisionReadAdapter(fixture.revisions, fixture.chunks),
		&schemaWikiRevisionBlobReaderSpy{},
		codec,
	)
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(10003))

	active, err := content.IssueExactRevision(ctx, fixture.request)
	require.NoError(t, err)
	activeRoute, err := content.ResolveRouteAuthority(ctx, active.OpaqueToken)
	require.NoError(t, err)
	require.Equal(t, "active", activeRoute.Kind)
	require.Equal(t, fixture.request.Scope, activeRoute.Scope)
	require.Empty(t, activeRoute.PreparationID)

	pdf := []byte("%PDF-1.7\npreparation route authority\n%%EOF")
	bindSchemaWikiCitationFixtureToBlob(t, &fixture, pdf)
	fixture.chunks.allChunks = []*types.Chunk{fixture.chunks.chunk}
	fixture.request.ReleaseID = ""
	fixture.request.ActivationEpoch = 0
	fixture.request.PreparationID = "preparation-596-1"
	fixture.request.EvaluationID = strings.Repeat("e", 64)
	fixture.request.EvidenceID = fixture.request.CoordinateAuthorityReceipt.ReceiptSHA256
	content = newSchemaWikiCitationContentService(
		newSchemaWikiCitationRevisionReadAdapter(
			fixture.revisions,
			fixture.chunks,
			&schemaWikiImmutableRevisionSnapshotReaderStub{
				authority: schemaWikiCitationPreviewAuthorityForFixture(t, fixture, pdf),
			},
		),
		&schemaWikiRevisionBlobReaderSpy{},
		codec,
	)
	preparation, err := content.IssuePreparationExactRevision(
		ctx,
		fixture.request.PreparationID,
		fixture.request.EvaluationID,
		fixture.request.EvidenceID,
		fixture.request,
	)
	require.NoError(t, err)
	preparationRoute, err := content.ResolveRouteAuthority(ctx, preparation.OpaqueToken)
	require.NoError(t, err)
	require.Equal(t, "preparation", preparationRoute.Kind)
	require.Equal(t, fixture.request.Scope, preparationRoute.Scope)
	require.Equal(t, fixture.request.PreparationID, preparationRoute.PreparationID)

	for _, invalid := range []string{
		"",
		"caller-supplied-current",
		active.OpaqueToken + "drift",
		preparation.OpaqueToken + "drift",
	} {
		resolved, resolveErr := content.ResolveRouteAuthority(ctx, invalid)
		require.Nil(t, resolved)
		require.ErrorIs(t, resolveErr, ErrSchemaWikiCitationUnavailable)
	}
}
