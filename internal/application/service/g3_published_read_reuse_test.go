package service

import (
	"encoding/json"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"os"
	"path/filepath"
	"testing"
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
	for i := 0; i < 2; i++ {
		got, rows, err := newPublishedBatchReadReuse830G3(sourceReuseTestCodec830G3(t)).read(p, p.WikiReleaseScope)
		require.NoError(t, err)
		require.Equal(t, bundle.CandidateHash, got.CandidateHash)
		require.Equal(t, members, rows)
	}
	for _, mutate := range []func(*types.WikiReleasePreparation){
		func(p *types.WikiReleasePreparation) { p.Manifest = append(p.Manifest, ' ') },
		func(p *types.WikiReleasePreparation) { p.Members[0].MemberDigest = "tampered" },
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
	_, _, err = store.read(p, p.WikiReleaseScope)
	require.Error(t, err, "a valid signature from another artifact domain cannot authorize a release read")
	require.Equal(t, full, batchPreparationValidations830G3.Load(), "published reads must reuse the validated release, not compile the full batch again")
}
