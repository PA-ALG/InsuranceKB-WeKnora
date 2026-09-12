package service

import (
	"context"
	"encoding/json"
	"github.com/Tencent/WeKnora/internal/types"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestConceptSourceReuse830G3PersistsAcrossServiceRestart(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	fixture, doc, scope, evidence, block := nativeIndexFixture830G2(t)
	readySourceReuseResource830G3(fixture)
	chunks := &conceptReuseCountingChunks830G3{delegate: fixture.chunks}
	fixed := &conceptReuseCountingFixed830G3{delegate: fixture.fixed}
	fixture.chunks, fixture.fixed = chunks, fixed
	open := func() *ConceptSourceAuthorityService830G2 {
		s := NewConceptSourceAuthorityService830G2(nil, nil, nil, nil, sourceReuseTestCodec830G3(t), nil, nil, nil)
		s.fixed, s.knowledge, s.revisions, s.chunks, s.docreader = fixture.fixed, fixture.knowledge, fixture.revisions, fixture.chunks, doc
		return s
	}
	first := open()
	_, bbox, err := first.verifyEvidence(context.Background(), scope, evidence, &block)
	require.NoError(t, err)
	_, again, err := first.verifyEvidence(context.Background(), scope, evidence, &block)
	require.NoError(t, err)
	require.Equal(t, bbox, again)
	require.Equal(t, 1, doc.calls, "a fresh HTTP request must reuse the fixed source capture")
	restarted := open()
	_, afterRestart, err := restarted.verifyEvidence(context.Background(), scope, evidence, &block)
	require.NoError(t, err)
	require.Equal(t, bbox, afterRestart)
	require.Equal(t, 1, doc.calls, "restarting must load the durable capture without invoking DocReader")
	require.Equal(t, 1, chunks.calls, "repeat requests and restart must not rescan database chunks")
	require.Equal(t, 1, fixed.calls, "locator reads must not reopen PDF bytes")
}

func TestConceptLegacyCarryover830G3FollowsValidatedPublishedParent(t *testing.T) {
	fixture, schema, bundle := batchConceptReleaseFixture830G3(t)
	draft, err := schema.CreateBatchConceptDraft830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		"batch-g3-source-parent", batchConceptCandidateVector830G3(t),
	)
	require.NoError(t, err)
	rawDecision, decision := conceptDecision830G2(t, fixture, draft, "batch-g3-source-parent")
	ready, err := schema.ReviewSchemaDraft(
		fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	receipt, err := fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, rawDecision,
		conceptAuthorization830G2(t, fixture, ready, decision),
	)
	require.NoError(t, err)
	release, err := fixture.repo.GetRelease(fixture.ctx, fixture.scope, receipt.ReleaseID)
	require.NoError(t, err)
	preparation, err := fixture.repo.GetReadyPreparation(fixture.ctx, fixture.scope, release.PreparationID)
	require.NoError(t, err)
	members, err := fixture.repo.GetReleaseMembers(fixture.ctx, fixture.scope, release.ID)
	require.NoError(t, err)

	parent, err := conceptLegacyCarryoverParent830G3(release, preparation, members, fixture.scope)
	require.NoError(t, err)
	require.Equal(t, bundle.Request.BaseRequest.BaseReleaseID, parent)

	members[0].MemberDigest = testSHA830G2("tampered-member")
	_, err = conceptLegacyCarryoverParent830G3(release, preparation, members, fixture.scope)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
}

func TestConceptSourceReuse830G3ReadDoesNotPrepareMissingCapture(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	fixture, doc, scope, evidence, block := nativeIndexFixture830G2(t)
	readySourceReuseResource830G3(fixture)
	s := NewConceptSourceAuthorityService830G2(nil, nil, nil, nil, sourceReuseTestCodec830G3(t), nil, nil, nil)
	s.fixed, s.knowledge, s.revisions, s.chunks, s.docreader = fixture.fixed, fixture.knowledge, fixture.revisions, fixture.chunks, doc
	_, _, _, err := s.verifyEvidenceLocated830G3(context.Background(), scope, evidence, &block, true)
	require.Error(t, err, "published reads need an explicitly prepared source artifact")
	require.Zero(t, doc.calls, "a published GET must never start a parser")
}

func readySourceReuseResource830G3(s *ConceptSourceAuthorityService830G2) {
	repo := s.revisions.(*conceptKnowledgeStub830G2)
	repo.resource.Handle = repo.source.ResourceHandle
	repo.resource.ContentHash = repo.source.ObjectSHA256
	repo.resource.State = types.ResourceStateActive
	repo.resource.Lifecycle = types.ResourceLifecyclePersistent
}

func TestConceptSourceReuse830G3PreparedImportAndCorruption(t *testing.T) {
	base := t.TempDir()
	t.Setenv("LOCAL_STORAGE_BASE_DIR", base)
	fixture, doc, scope, evidence, block := nativeIndexFixture830G2(t)
	readySourceReuseResource830G3(fixture)
	open := func() *ConceptSourceAuthorityService830G2 {
		s := NewConceptSourceAuthorityService830G2(nil, nil, nil, nil, sourceReuseTestCodec830G3(t), nil, nil, nil)
		s.fixed, s.knowledge, s.revisions, s.chunks, s.docreader = fixture.fixed, fixture.knowledge, fixture.revisions, fixture.chunks, doc
		return s
	}
	s := open()
	// Existing native capture is imported without another parser call.
	require.NoError(t, s.PrepareConceptSourceReuse830G3(context.Background(), scope, evidence, block, doc.result))
	require.Zero(t, doc.calls)
	_, _, _, err := open().verifyEvidenceLocated830G3(context.Background(), scope, evidence, &block, true)
	require.NoError(t, err)
	require.Zero(t, doc.calls)
	// The stored derived data cannot override the fixed revision manifest.
	paths, err := filepath.Glob(filepath.Join(base, ".concept-source-reuse-v1", "*.json"))
	require.NoError(t, err)
	require.Len(t, paths, 1)
	require.NoError(t, os.WriteFile(paths[0], []byte(`{"contract":"corrupt"}`), 0600))
	_, _, _, err = open().verifyEvidenceLocated830G3(context.Background(), scope, evidence, &block, true)
	require.Error(t, err)
	require.Zero(t, doc.calls, "corruption must not trigger hidden parser retries")
}

func TestConceptSourceReuse830G3ConcurrentPreparationAndLiveChecks(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	fixture, doc, scope, evidence, block := nativeIndexFixture830G2(t)
	readySourceReuseResource830G3(fixture)
	s := NewConceptSourceAuthorityService830G2(nil, nil, nil, nil, sourceReuseTestCodec830G3(t), nil, nil, nil)
	s.fixed, s.knowledge, s.revisions, s.chunks, s.docreader = fixture.fixed, fixture.knowledge, fixture.revisions, fixture.chunks, doc
	var wg sync.WaitGroup
	errs := make(chan error, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			errs <- s.PrepareConceptSourceReuse830G3(context.Background(), scope, evidence, block, nil)
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		require.NoError(t, err)
	}
	require.Equal(t, 1, doc.calls)
	bad := evidence
	bad.Quote = "missing"
	bad.QuoteHash = testSHA830G2(bad.Quote)
	_, _, _, err := s.verifyEvidenceLocated830G3(context.Background(), scope, bad, &block, true)
	require.Error(t, err)
	repo := fixture.revisions.(*conceptKnowledgeStub830G2)
	repo.resource.State = "deleted"
	_, _, _, err = s.verifyEvidenceLocated830G3(context.Background(), scope, evidence, &block, true)
	require.Error(t, err, "resource revocation is checked even with a resident index")
	require.Equal(t, 1, doc.calls)
}

func TestConceptSourceReuse830G3LegacyProofPreparationSurvivesRestart(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	fixture, request, _ := cfg42LegacyDigestFixture(t)
	request.Bundle.CandidateHash = testSHA830G2("validated-child-candidate")
	request.Bundle.Request.BaseReleaseID = "published-base"
	readyLegacySourceReuseFixture830G3(t, fixture, request)
	calls := 0
	resolver := fixture.legacyProofResolver
	open := func() *ConceptSourceAuthorityService830G2 {
		s := NewConceptSourceAuthorityService830G2(nil, nil, nil, nil, fixture.codec, nil, nil, nil)
		s.knowledge, s.revisions = fixture.knowledge, fixture.revisions
		s.legacyProofResolver = func(ctx context.Context, scope types.WikiReleaseScope, bundle types.ConceptCandidateBundle830G2) (map[string]conceptLegacyProof830G2, error) {
			calls++
			return resolver(ctx, scope, bundle)
		}
		return s
	}
	ctx := context.WithValue(context.Background(), conceptSourceReusePrepareKey830G3{}, true)
	_, err := open().verifyLegacyCarryover830G2(ctx, request.Scope, *request.Bundle)
	require.NoError(t, err)
	_, err = open().verifyLegacyCarryover830G2(ctx, request.Scope, *request.Bundle)
	require.NoError(t, err)
	require.Equal(t, 1, calls, "restart must reuse admitted legacy proofs instead of replaying the release chain")
}

func sourceReuseTestCodec830G3(t *testing.T) *SchemaWikiCitationTokenCodec {
	s, _ := cfg42AuthorityFixture(t)
	return s.codec
}

func TestConceptSourceReuse830G3DerivedArtifactCannotSelfAuthorize(t *testing.T) {
	base := t.TempDir()
	t.Setenv("LOCAL_STORAGE_BASE_DIR", base)
	fixture, doc, scope, evidence, block := nativeIndexFixture830G2(t)
	readySourceReuseResource830G3(fixture)
	open := func() *ConceptSourceAuthorityService830G2 {
		s := NewConceptSourceAuthorityService830G2(nil, nil, nil, nil, sourceReuseTestCodec830G3(t), nil, nil, nil)
		s.fixed, s.knowledge, s.revisions, s.chunks, s.docreader = fixture.fixed, fixture.knowledge, fixture.revisions, fixture.chunks, doc
		return s
	}
	require.NoError(t, open().PrepareConceptSourceReuse830G3(context.Background(), scope, evidence, block, doc.result))
	paths, err := filepath.Glob(filepath.Join(base, ".concept-source-reuse-v1", "*.json"))
	require.NoError(t, err)
	require.Len(t, paths, 1)
	data, err := os.ReadFile(paths[0])
	require.NoError(t, err)
	// Replace the artifact with structurally valid self-hashed data. A reader
	// must require the preparation signature, not accept these self-reports.
	var record conceptSourceReuseRecord830G3
	require.NoError(t, json.Unmarshal(data, &record))
	if record.Native == nil { // The implementation seals the payload in an envelope.
		var outer struct {
			Payload json.RawMessage `json:"payload"`
		}
		require.NoError(t, json.Unmarshal(data, &outer))
		require.NoError(t, json.Unmarshal(outer.Payload, &record))
	}
	var projection conceptNativeProjection830G2
	require.NoError(t, json.Unmarshal(record.Native.SanitizedJSON, &projection))
	projection.Pages[0].BBoxes[0].BBox[0]++
	record.Native.SanitizedJSON, err = canonicalJSON830G2(projection)
	require.NoError(t, err)
	record.Native.SanitizedSHA256 = testSHA256Bytes830G2(record.Native.SanitizedJSON)
	record.Native.RawSHA256 = record.Native.SanitizedSHA256
	data, err = json.Marshal(record)
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(paths[0], data, 0600))
	_, _, _, err = open().verifyEvidenceLocated830G3(context.Background(), scope, evidence, &block, true)
	require.Error(t, err, "self-hashed locator data is not an admitted capture")
	require.Zero(t, doc.calls)
}

type conceptReuseCountingChunks830G3 struct {
	delegate conceptChunkReader830G2
	calls    int
}

func (c *conceptReuseCountingChunks830G3) ListChunksByKnowledgeID(ctx context.Context, tenant uint64, knowledge string) ([]*types.Chunk, error) {
	c.calls++
	return c.delegate.ListChunksByKnowledgeID(ctx, tenant, knowledge)
}

type conceptReuseCountingFixed830G3 struct {
	delegate conceptFixedRevisionReader830G2
	calls    int
}

func (c *conceptReuseCountingFixed830G3) ReadFixedRevision(ctx context.Context, knowledge string, attempt int64, file, binding string, page int) ([]byte, error) {
	c.calls++
	return c.delegate.ReadFixedRevision(ctx, knowledge, attempt, file, binding, page)
}

func TestConceptSourceReuse830G3FailedPreparationStaysExplicit(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	fixture, doc, scope, evidence, block := nativeIndexFixture830G2(t)
	readySourceReuseResource830G3(fixture)
	s := NewConceptSourceAuthorityService830G2(nil, nil, nil, nil, sourceReuseTestCodec830G3(t), nil, nil, nil)
	s.fixed, s.knowledge, s.revisions, s.chunks, s.docreader = fixture.fixed, fixture.knowledge, fixture.revisions, fixture.chunks, doc
	doc.result.NativeStructure.SanitizedJSON[0] = '!'
	require.Error(t, s.PrepareConceptSourceReuse830G3(context.Background(), scope, evidence, block, nil))
	require.Equal(t, 1, doc.calls)
	_, _, _, err := s.verifyEvidenceLocated830G3(context.Background(), scope, evidence, &block, true)
	require.Error(t, err)
	require.Equal(t, 1, doc.calls, "GET after a failed preparation cannot retry parsing")
	doc.result, _ = testNativeResult830G2(t)
	require.NoError(t, s.PrepareConceptSourceReuse830G3(context.Background(), scope, evidence, block, nil))
	require.Equal(t, 2, doc.calls, "only an explicit second preparation may retry")
}

func TestConceptSourceReuse830G3LegacyReadNeverReplaysMissingProof(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	fixture, request, _ := cfg42LegacyDigestFixture(t)
	request.Bundle.CandidateHash = testSHA830G2("validated-child-candidate")
	request.Bundle.Request.BaseReleaseID = "published-base"
	readyLegacySourceReuseFixture830G3(t, fixture, request)
	s := NewConceptSourceAuthorityService830G2(nil, nil, nil, nil, fixture.codec, nil, nil, nil)
	s.knowledge, s.revisions = fixture.knowledge, fixture.revisions
	calls := 0
	s.legacyProofResolver = func(ctx context.Context, scope types.WikiReleaseScope, b types.ConceptCandidateBundle830G2) (map[string]conceptLegacyProof830G2, error) {
		calls++
		return fixture.legacyProofResolver(ctx, scope, b)
	}
	ctx := context.WithValue(context.Background(), conceptSourceReuseReadOnlyKey830G3{}, true)
	_, err := s.verifyLegacyCarryover830G2(ctx, request.Scope, *request.Bundle)
	require.Error(t, err)
	require.Zero(t, calls)
	require.NoError(t, s.PrepareConceptLegacySourceReuse830G3(context.Background(), request.Scope, *request.Bundle))
	_, err = s.verifyLegacyCarryover830G2(ctx, request.Scope, *request.Bundle)
	require.NoError(t, err)
	require.Equal(t, 1, calls)
}

func TestConceptDerivedArtifact830G3DomainAndKeyIsolation(t *testing.T) {
	codec := sourceReuseTestCodec830G3(t)
	encoded, err := sealConceptDerivedArtifact830G3(codec, "source-domain", "revision-a", []byte(`{"verified":true}`))
	require.NoError(t, err)
	_, err = openConceptDerivedArtifact830G3(codec, "published-domain", "revision-a", encoded)
	require.Error(t, err)
	_, err = openConceptDerivedArtifact830G3(codec, "source-domain", "revision-b", encoded)
	require.Error(t, err)
	decoded, err := openConceptDerivedArtifact830G3(codec, "source-domain", "revision-a", encoded)
	require.NoError(t, err)
	require.JSONEq(t, `{"verified":true}`, string(decoded))
	delete(codec.publicKeys, codec.activeKeyID)
	_, err = openConceptDerivedArtifact830G3(codec, "source-domain", "revision-a", encoded)
	require.Error(t, err)
}

func readyLegacySourceReuseFixture830G3(t *testing.T, fixture *ConceptSourceAuthorityService830G2, request ConceptCitationAuthorityRequest830G2) {
	t.Helper()
	readySourceReuseResource830G3(fixture)
	repo := fixture.revisions.(*conceptKnowledgeStub830G2)
	repo.revision.ManifestDigest = repo.source.ManifestDigest
	proofs, err := fixture.legacyProofResolver(context.Background(), request.Scope, *request.Bundle)
	require.NoError(t, err)
	for _, proof := range proofs {
		r := &proof.authority.RevisionSource
		r.TenantID = repo.source.TenantID
		r.KnowledgeID = repo.source.KnowledgeID
		r.WeKnoraParseAttempt = repo.source.ParseAttempt
		r.FileSHA256 = repo.source.FileSHA256
		r.ResourceID = repo.source.ResourceID
		r.PageCount = *repo.source.PageCount
		r.WeKnoraManifestAlgorithm = repo.source.ManifestAlgorithm
		r.WeKnoraManifestDigest = repo.source.ManifestDigest
		r.WeKnoraChunkCount = repo.source.ChunkCount
	}
}

func TestConceptLegacyPreparedProofStillChecksCurrentSourceAtPublicationGate(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	fixture, request, _ := cfg42LegacyDigestFixture(t)
	request.Bundle.CandidateHash = testSHA830G2("validated-child-candidate")
	request.Bundle.Request.BaseReleaseID = "published-base"
	readyLegacySourceReuseFixture830G3(t, fixture, request)
	s := NewConceptSourceAuthorityService830G2(nil, nil, nil, nil, fixture.codec, nil, nil, nil)
	s.knowledge, s.revisions = fixture.knowledge, fixture.revisions
	calls := 0
	s.legacyProofResolver = func(ctx context.Context, scope types.WikiReleaseScope, b types.ConceptCandidateBundle830G2) (map[string]conceptLegacyProof830G2, error) {
		calls++
		return fixture.legacyProofResolver(ctx, scope, b)
	}
	ctx := context.WithValue(context.Background(), conceptSourceReusePrepareKey830G3{}, true)
	_, err := s.verifyLegacyCarryover830G2(ctx, request.Scope, *request.Bundle)
	require.NoError(t, err)
	_, err = s.verifyLegacyCarryover830G2(ctx, request.Scope, *request.Bundle)
	require.NoError(t, err)
	require.Equal(t, 1, calls)
	repo := fixture.revisions.(*conceptKnowledgeStub830G2)
	repo.resource.State = "deleted"
	_, err = s.verifyLegacyCarryover830G2(ctx, request.Scope, *request.Bundle)
	require.Error(t, err, "review/activate/prepare-read cannot reuse a proof whose source was revoked")
	require.Equal(t, 1, calls, "current checks must not replay immutable history")
}
