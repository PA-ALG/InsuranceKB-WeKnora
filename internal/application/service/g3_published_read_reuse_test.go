package service

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestPublishedBatchReadDoesNotRepeatSemanticCompilation(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	bundle, raw, err := types.CanonicalBatchConceptCandidateBundle830G3(batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	members, err := bundle.SnapshotMembers()
	require.NoError(t, err)
	base := bundle.Request.BaseRequest
	p := &types.WikiReleasePreparation{ID: "read-reuse", WikiReleaseScope: batchConceptScope830G3(bundle), Status: types.WikiReleasePreparationReady, Manifest: raw, Members: members, CandidateDigest: bundle.CandidateHash, ManifestDigest: digestWikiReleaseBytes(raw), ReadyReceiptDigest: bundle.ReviewResult.Execution.RawOutputHash, ReviewDecisionDigest: "reviewed", ReviewPolicyID: conceptReviewPolicyHash830G2(base.PolicyIdentity), ExpectedReleaseID: base.BaseReleaseID, ExpectedActivationEpoch: base.BaseActivationEpoch}
	p.PreparationDigest = digestWikiReleasePreparation(p)
	_, _, err = validateBatchConceptPreparation830G3(p, types.WikiReleasePreparationReady, p.WikiReleaseScope)
	require.NoError(t, err)
	store := newPublishedBatchReadReuse830G3(sourceReuseTestCodec830G3(t))
	beforeMissing := batchPreparationValidations830G3.Load()
	_, _, err = store.read(p, p.WikiReleaseScope)
	require.Error(t, err, "an unprepared read must not compile implicitly")
	require.Equal(t, beforeMissing, batchPreparationValidations830G3.Load())
	require.NoError(t, store.rememberValidated(p, p.WikiReleaseScope))
	full := batchPreparationValidations830G3.Load()
	metadata := *p
	metadata.Manifest = nil
	metadata.Members = nil
	for i := 0; i < 2; i++ {
		got, rows, err := newPublishedBatchReadReuse830G3(sourceReuseTestCodec830G3(t)).read(&metadata, p.WikiReleaseScope)
		require.NoError(t, err)
		require.Equal(t, bundle.CandidateHash, got.CandidateHash)
		require.Equal(t, members, rows)
		require.Empty(t, got.ModelCompileResult.Execution.RawOutput)
		require.Empty(t, got.CompileResult.Execution.RawOutput)
	}
	driftedRows := append([]types.WikiReleaseMemberSnapshot(nil), members...)
	driftedRows[0].MemberDigest = "tampered"
	require.True(t, publishedBatchMemberIdentitiesEqual830G3(members, members))
	require.False(t, publishedBatchMemberIdentitiesEqual830G3(members, driftedRows))
	for _, mutate := range []func(*types.WikiReleasePreparation){
		func(p *types.WikiReleasePreparation) { p.Manifest = append(p.Manifest, ' ') },
		func(p *types.WikiReleasePreparation) { p.Members[0].MemberDigest = "tampered" },
		func(p *types.WikiReleasePreparation) {
			p.ManifestDigest = digestWikiReleaseBytes([]byte("other manifest"))
			p.PreparationDigest = digestWikiReleasePreparation(p)
		},
		func(p *types.WikiReleasePreparation) {
			p.ExpectedActivationEpoch++
			p.PreparationDigest = digestWikiReleasePreparation(p)
		},
	} {
		var changed types.WikiReleasePreparation
		raw, err := json.Marshal(p)
		require.NoError(t, err)
		require.NoError(t, json.Unmarshal(raw, &changed))
		mutate(&changed)
		_, _, err = store.read(&changed, changed.WikiReleaseScope)
		require.Error(t, err, "changed persisted input must require explicit revalidation")
	}
	key, err := publishedBatchInputKey830G3(p, p.WikiReleaseScope)
	require.NoError(t, err)
	wrongDomain, err := sealConceptDerivedArtifact830G3(store.codec, "another-domain", key, []byte(`"`+p.CandidateDigest+`"`))
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(filepath.Join(store.root, key+".json"), wrongDomain, 0600))
	_, _, err = newPublishedBatchReadReuse830G3(sourceReuseTestCodec830G3(t)).read(p, p.WikiReleaseScope)
	require.Error(t, err, "a valid signature from another artifact domain cannot authorize a release read")

	legacy := *p
	legacy.ID = "legacy-read-reuse"
	legacy.PreparationDigest = digestWikiReleasePreparation(&legacy)
	legacyKey, err := publishedBatchLegacyInputKey830G3(&legacy, legacy.WikiReleaseScope)
	require.NoError(t, err)
	legacyPayload, err := json.Marshal(legacy.CandidateDigest)
	require.NoError(t, err)
	legacySeal, err := sealConceptDerivedArtifact830G3(
		store.codec, publishedBatchLegacyReuseDomain830G3, legacyKey, legacyPayload,
	)
	require.NoError(t, err)
	legacyRoot := filepath.Join(filepath.Dir(store.root), ".concept-published-read-v1")
	require.NoError(t, os.MkdirAll(legacyRoot, 0700))
	require.NoError(t, os.WriteFile(filepath.Join(legacyRoot, legacyKey+".json"), legacySeal, 0600))
	legacyBundle, legacyMembers, err := (&WikiReleaseService{publishedReadReuse: store}).
		validatePublishedBatchConceptPreparation830G3(&legacy, legacy.WikiReleaseScope)
	require.NoError(t, err)
	require.Equal(t, bundle.CandidateHash, legacyBundle.CandidateHash)
	require.Equal(t, members, legacyMembers)
	require.Equal(t, full, batchPreparationValidations830G3.Load(), "published reads must reuse the validated release, not compile the full batch again")
}

func TestPublishedBatchReadProjectionCarriesNavigationAssignment(t *testing.T) {
	row := types.NavigationAssignment830G3{Contract: "g3-navigation-assignment.830.v1", EntityID: "entity", EntityVersion: "v1", AssignmentVersion: 1, Labels: []string{"健康保障"}, PrimaryLabel: "健康保障", PreviousAssignmentSHA256: "parent", AssignmentSHA256: "assignment"}
	bundle := types.BatchConceptCandidateBundle830G3{NavigationAssignments: []types.NavigationAssignment830G3{row}}
	projection := publishedBatchProjectedBundle830G3(bundle)
	require.Equal(t, bundle.NavigationAssignments, projection.NavigationAssignments)
	raw, err := json.Marshal(projection)
	require.NoError(t, err)
	var reopened types.BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(raw, &reopened))
	require.Equal(t, bundle.NavigationAssignments, reopened.NavigationAssignments)
}
