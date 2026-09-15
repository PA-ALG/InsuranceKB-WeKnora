package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

// Real fixture release/projection owners are used here. The empty sealed legacy
// set models a published baseline with no carried G1 occurrences; it is distinct
// from a missing proof. No provider or real application database is involved.
func TestG3RecentPublishedBaselineAvoidsAncestorReplay(t *testing.T) {
	f, schema, parent := batchConceptReleaseFixture830G3(t)
	draft, err := schema.CreateBatchConceptDraft830G3(f.ctx, f.principal1, f.scope,
		"g3-recent-proof-parent", batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	rawDecision, decision := conceptDecision830G2(t, f, draft, draft.ID)
	ready, err := schema.ReviewSchemaDraft(f.ctx, f.principal1, f.scope, draft.ID, rawDecision)
	require.NoError(t, err)
	published, err := f.service.ActivateReviewed(f.ctx, f.principal1, rawDecision,
		conceptAuthorization830G2(t, f, ready, decision))
	require.NoError(t, err)

	codec := sourceReuseTestCodec830G3(t)
	store := newConceptSourceReuseStore830G3(codec)
	base := parent.Request.BaseRequest
	identity, err := canonicalJSON830G2(struct {
		Scope           types.WikiReleaseScope
		Candidate, Base string
		Epoch           uint64
	}{f.scope, parent.CandidateHash, base.BaseReleaseID, base.BaseActivationEpoch})
	require.NoError(t, err)
	key := "legacy-" + testSHA256Bytes830G2(identity)
	require.NoError(t, store.writeArtifact(filepath.Join(store.root, key+".json"), key, []byte(`{}`)))
	child := types.ConceptCandidateBundle830G2{CandidateHash: testSHA830G2("new-incremental-child"), Request: base}
	child.Request.BaseReleaseID, child.Request.BaseActivationEpoch = published.ReleaseID, published.ActivationEpoch
	child.Request.ExistingFields = parent.CompileResult.Output.Fields
	child.CompileResult.Output.Fields = parent.CompileResult.Output.Fields
	before, err := json.Marshal(child)
	require.NoError(t, err)
	calls := 0
	fullValidations := batchPreparationValidations830G3.Load()
	for i := 0; i < 2; i++ {
		child.CandidateHash = testSHA830G2(fmt.Sprintf("new-incremental-child-%d", i))
		authority := NewConceptSourceAuthorityService830G2(nil, nil, nil, nil, codec, f.repo, nil, nil)
		authority.legacyProofResolver = func(context.Context, types.WikiReleaseScope, types.ConceptCandidateBundle830G2) (map[string]conceptLegacyProof830G2, error) {
			calls++
			return nil, errors.New("unexpected complete ancestor replay")
		}
		owner := NewWikiReleaseService(f.repo, f.service.accessVerifier, f.service.authorizationVerifier,
			WikiReleaseServiceOptions{ConceptSourceAuthorityVerifier830G2: authority})
		require.NotNil(t, owner)
		ctx := context.WithValue(f.ctx, conceptSourceReusePrepareKey830G3{}, true)
		proofs, err := authority.verifyLegacyCarryover830G2(ctx, f.scope, child)
		require.NoError(t, err, "an existing signed G3 baseline must be consumed before replaying ancestors")
		require.Empty(t, proofs)
	}
	require.Zero(t, calls)
	require.Equal(t, fullValidations, batchPreparationValidations830G3.Load(), "cold baseline reads must not fully revalidate historical candidates")
	child.CandidateHash = testSHA830G2("new-incremental-child")
	after, err := json.Marshal(child)
	require.NoError(t, err)
	require.Equal(t, before, after)
	owner := NewWikiReleaseService(f.repo, f.service.accessVerifier, f.service.authorizationVerifier,
		WikiReleaseServiceOptions{ConceptSourceAuthorityVerifier830G2: NewConceptSourceAuthorityService830G2(nil, nil, nil, nil, codec, f.repo, nil, nil)})
	_, _, err = owner.loadPublishedLegacyBase830G3(f.ctx, f.scope, published.ReleaseID, published.ActivationEpoch+1)
	require.Error(t, err)
	foreign := f.scope
	foreign.SpaceID = "another-space"
	_, _, err = owner.loadPublishedLegacyBase830G3(f.ctx, foreign, published.ReleaseID, published.ActivationEpoch)
	require.Error(t, err)
	projectionPath, err := owner.publishedBatchReuse830G3().artifactPath(ready, f.scope)
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(projectionPath, []byte(`{}`), 0600))
	_, _, err = owner.loadPublishedLegacyBase830G3(f.ctx, f.scope, published.ReleaseID, published.ActivationEpoch)
	require.Error(t, err, "corrupt published projection cannot silently fall back")
	require.NoError(t, os.Remove(projectionPath))
	_, found, err := owner.loadPublishedLegacyBase830G3(f.ctx, f.scope, published.ReleaseID, published.ActivationEpoch)
	require.NoError(t, err)
	require.False(t, found, "missing projection retains the established prepare path")
}

func TestG3PublishedLegacyOccurrencesPreserveFactsAndRejectUnboundProof(t *testing.T) {
	value := "covered"
	field := types.ConceptFieldAssertion830G2{SpaceID: "space", EntityID: "entity", FieldKey: "field", State: "present", Value: &value,
		Attempted: true, EntityVersion: "v1", Evidence: []types.ConceptEvidence830G2{{Quote: "same original", QuoteHash: testSHA830G2("same original"), PageNumber: 2, Start: 3, End: 16}}}
	id, err := field.FieldAssertionID()
	require.NoError(t, err)
	evidence, err := canonicalJSON830G2(field.Evidence[0])
	require.NoError(t, err)
	key := id + "\x00" + testSHA256Bytes830G2(evidence)
	proof := &types.SchemaWikiCitationContentAuthorityV1{PageNumber: 2}
	wire := map[string]*types.SchemaWikiCitationContentAuthorityV1{key: proof}
	for _, name := range []string{"unchanged", "navigation", "value", "conditions", "exceptions", "quote", "page", "offset", "source", "parser", "new field", "new version"} {
		t.Run(name, func(t *testing.T) {
			raw, err := json.Marshal(field)
			require.NoError(t, err)
			var next types.ConceptFieldAssertion830G2
			require.NoError(t, json.Unmarshal(raw, &next))
			switch name {
			case "navigation":
				next.ConceptIDs = []string{"added"}
			case "value":
				changed := "changed"
				next.Value = &changed
			case "conditions":
				next.Conditions = []string{"new condition"}
			case "exceptions":
				next.Exceptions = []string{"new exception"}
			case "quote":
				next.Evidence[0].Quote = "different"
			case "page":
				next.Evidence[0].PageNumber++
			case "offset":
				next.Evidence[0].Start++
			case "source":
				next.Evidence[0].SourceHash = "different"
			case "parser":
				next.Evidence[0].ParserIdentity = "different"
			case "new field":
				next.FieldKey = "different"
			case "new version":
				next.EntityVersion = "v2"
			}
			child := types.ConceptCandidateBundle830G2{}
			child.Request.ExistingFields = []types.ConceptFieldAssertion830G2{field}
			child.CompileResult.Output.Fields = []types.ConceptFieldAssertion830G2{next}
			got, err := remapPublishedLegacyOccurrences830G3([]types.ConceptFieldAssertion830G2{field}, child, wire)
			require.NoError(t, err)
			if name == "unchanged" || name == "navigation" {
				require.Len(t, got, 1)
				require.Equal(t, proof, got[key].authority)
			} else {
				require.Empty(t, got)
			}
		})
	}
	_, err = remapPublishedLegacyOccurrences830G3(nil, types.ConceptCandidateBundle830G2{}, wire)
	require.Error(t, err, "a signed proof must still belong to an actual parent occurrence")
}

func TestG3PublishedLegacyProofStillChecksSignatureMissingAndRevocation(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	s, request, proof := cfg42LegacyDigestFixture(t)
	s.sourceReuse = newConceptSourceReuseStore830G3(s.codec)
	readyLegacySourceReuseFixture830G3(t, s, request)
	value := "original"
	field := types.ConceptFieldAssertion830G2{SpaceID: request.Scope.SpaceID, EntityID: "entity", FieldKey: "field", State: "present", Value: &value,
		Attempted: true, Evidence: []types.ConceptEvidence830G2{request.Evidence}, EntityVersion: "v1"}
	parent := types.BatchConceptCandidateBundle830G3{CandidateHash: testSHA830G2("parent")}
	parent.Request.BaseRequest.BaseReleaseID, parent.Request.BaseRequest.BaseActivationEpoch = "older-parent", 4
	parent.CompileResult.Output.Fields = []types.ConceptFieldAssertion830G2{field}
	key := conceptLegacyProofKey830G3(request.Scope, parent.CandidateHash, "older-parent", 4)
	member, err := field.FieldAssertionID()
	require.NoError(t, err)
	evidence, err := canonicalJSON830G2(request.Evidence)
	require.NoError(t, err)
	wire, err := json.Marshal(map[string]*types.SchemaWikiCitationContentAuthorityV1{member + "\x00" + testSHA256Bytes830G2(evidence): proof})
	require.NoError(t, err)
	path := filepath.Join(s.sourceReuse.root, key+".json")
	require.NoError(t, s.sourceReuse.writeArtifact(path, key, wire))
	sealed, err := os.ReadFile(path)
	require.NoError(t, err)
	s.publishedLegacyBase = func(_ context.Context, scope types.WikiReleaseScope, id string, epoch uint64) (types.BatchConceptCandidateBundle830G3, bool, error) {
		require.Equal(t, request.Scope, scope)
		require.Equal(t, "recent-parent", id)
		require.EqualValues(t, 5, epoch)
		return parent, true, nil
	}
	calls := 0
	s.legacyProofResolver = func(context.Context, types.WikiReleaseScope, types.ConceptCandidateBundle830G2) (map[string]conceptLegacyProof830G2, error) {
		calls++
		return nil, errors.New("missing baseline needs original preparation")
	}
	child := types.ConceptCandidateBundle830G2{CandidateHash: testSHA830G2("child")}
	child.Request.BaseReleaseID, child.Request.BaseActivationEpoch = "recent-parent", 5
	child.Request.ExistingFields, child.CompileResult.Output.Fields = []types.ConceptFieldAssertion830G2{field}, []types.ConceptFieldAssertion830G2{field}
	ctx := context.WithValue(context.Background(), conceptSourceReusePrepareKey830G3{}, true)
	got, err := s.verifyLegacyCarryover830G2(ctx, request.Scope, child)
	require.NoError(t, err)
	require.Len(t, got, 1)
	require.Zero(t, calls)
	after, err := os.ReadFile(path)
	require.NoError(t, err)
	require.Equal(t, sealed, after)
	repo := s.revisions.(*conceptKnowledgeStub830G2)
	resourceState := repo.resource.State
	repo.resource.State = "deleted"
	_, err = s.verifyLegacyCarryover830G2(ctx, request.Scope, child)
	require.Error(t, err)
	require.Zero(t, calls)
	repo.resource.State = resourceState
	child.CandidateHash = testSHA830G2("other-child")
	require.NoError(t, os.WriteFile(path, []byte(`{"key":"wrong","payload":{},"signature":""}`), 0600))
	_, err = s.verifyLegacyCarryover830G2(ctx, request.Scope, child)
	require.Error(t, err)
	require.Zero(t, calls, "corrupt proof cannot silently trigger reconstruction")
	require.NoError(t, os.Remove(path))
	_, err = s.verifyLegacyCarryover830G2(ctx, request.Scope, child)
	require.Error(t, err)
	require.Equal(t, 1, calls, "missing proof alone retains the explicit preparation fallback")
}

func TestG3LegacyNavigationCarryAcceptsColdOptionalCollections(t *testing.T) {
	value := "covered"
	parent := types.ConceptFieldAssertion830G2{SpaceID: "s", EntityID: "e", FieldKey: "f",
		State: "present", Value: &value, Attempted: true, Evidence: []types.ConceptEvidence830G2{{Quote: "same"}},
		EntityVersion: "v1"}
	existing := parent
	existing.ConceptIDs, existing.Conditions, existing.Exceptions = []string{}, []string{}, []string{}
	child := existing
	child.ConceptIDs = []string{"additional-navigation"}
	got, ok := conceptLegacyCarryoverTargetField830G2(parent, []types.ConceptFieldAssertion830G2{existing}, []types.ConceptFieldAssertion830G2{child})
	require.True(t, ok, "signed gob optional nil collections are equivalent to empty wire collections")
	require.Equal(t, child, got)
}
