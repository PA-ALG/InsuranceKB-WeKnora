package service

import (
	"encoding/json"
	"os"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

// Optional diagnostic replays the exact already-published candidate, no model or DB writes.
func TestG3PublishedReadCost(t *testing.T) {
	path := os.Getenv("G3_READ_COST_CANDIDATE")
	if path == "" {
		t.Skip("explicit representative candidate required")
	}
	start := time.Now()
	raw, err := os.ReadFile(path)
	require.NoError(t, err)
	t.Logf("read bytes=%d elapsed=%s", len(raw), time.Since(start))
	start = time.Now()
	var decoded types.BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(raw, &decoded))
	t.Logf("JSON decode=%s", time.Since(start))
	start = time.Now()
	bundle, _, err := types.CanonicalBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	t.Logf("full candidate validation=%s", time.Since(start))
	start = time.Now()
	rows, err := bundle.SnapshotMembers()
	require.NoError(t, err)
	t.Logf("SnapshotMembers revalidation rows=%d elapsed=%s", len(rows), time.Since(start))
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	base := bundle.Request.BaseRequest
	p := &types.WikiReleasePreparation{ID: "actual-read-cost", WikiReleaseScope: batchConceptScope830G3(bundle), Status: types.WikiReleasePreparationReady, Manifest: raw, Members: rows, CandidateDigest: bundle.CandidateHash, ManifestDigest: digestWikiReleaseBytes(raw), ReadyReceiptDigest: bundle.ReviewResult.Execution.RawOutputHash, ReviewDecisionDigest: "reviewed", ReviewPolicyID: conceptReviewPolicyHash830G2(base.PolicyIdentity), ExpectedReleaseID: base.BaseReleaseID, ExpectedActivationEpoch: base.BaseActivationEpoch}
	p.PreparationDigest = digestWikiReleasePreparation(p)
	store := newPublishedBatchReadReuse830G3(sourceReuseTestCodec830G3(t))
	require.NoError(t, store.rememberValidated(p, p.WikiReleaseScope))
	full := batchPreparationValidations830G3.Load()
	metadata := *p
	metadata.Manifest = nil
	metadata.Members = nil
	artifactPath, err := store.artifactPath(&metadata, metadata.WikiReleaseScope)
	require.NoError(t, err)
	info, err := os.Stat(artifactPath)
	require.NoError(t, err)
	t.Logf("published projection bytes=%d candidate_ratio=%.3f", info.Size(), float64(info.Size())/float64(len(raw)))
	for i := 0; i < 2; i++ {
		start = time.Now()
		result, members, err := store.read(&metadata, p.WikiReleaseScope)
		require.NoError(t, err)
		require.Equal(t, bundle.CandidateHash, result.CandidateHash)
		require.Equal(t, len(rows), len(members))
		t.Logf("prepared read/warm process attempt=%d elapsed=%s", i+1, time.Since(start))
	}
	restarted := newPublishedBatchReadReuse830G3(sourceReuseTestCodec830G3(t))
	for i := 0; i < 2; i++ {
		start = time.Now()
		result, members, err := restarted.read(&metadata, p.WikiReleaseScope)
		require.NoError(t, err)
		require.Equal(t, bundle.CandidateHash, result.CandidateHash)
		require.Equal(t, len(rows), len(members))
		t.Logf("prepared read/restarted process attempt=%d elapsed=%s", i+1, time.Since(start))
	}
	require.Equal(t, full, batchPreparationValidations830G3.Load())

}
