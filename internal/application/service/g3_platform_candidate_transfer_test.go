package service

import (
	"encoding/json"
	"errors"
	"os"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestG3CandidateTransferUsesExistingDraftAuthorityAndExactManifest(t *testing.T) {
	f, s, policy := automatedFixture(t)
	parent, err := s.CreateBatchConceptDraftAutomated830G3(f.ctx, f.principal1, f.scope, "transfer-parent", batchConceptCandidateVector830G3(t))
	require.NoError(t, err)
	decision, signedDecision := automaticDecision(t, f, policy, parent)
	ready, err := f.service.ReviewDraftAutomated(f.ctx, f.principal1, f.scope, parent.ID, decision)
	require.NoError(t, err)
	oldID := f.service.newID
	f.service.newID = func(kind string) string {
		if kind == "release" {
			return "release-platform-parent"
		}
		return oldID(kind)
	}
	_, err = f.service.ActivateAutomated(f.ctx, f.principal1, decision, automaticAuthorization(t, f, ready, signedDecision.Nonce))
	require.NoError(t, err)
	f.service.newID = oldID
	// Exercise the next draft after process-local caches are gone, not only the
	// warm projection produced by the immediately preceding activation.
	f.service.publishedBatchReuse830G3().entries = map[string]publishedBatchReadCache830G3{}
	transfer, err := os.ReadFile("../../../harness/tests/fixtures/batch_concept_compile_830_g3/platform-incremental-transfer.json")
	require.NoError(t, err)
	candidate, err := os.ReadFile("../../../harness/tests/fixtures/batch_concept_compile_830_g3/platform-incremental-candidate.json")
	require.NoError(t, err)
	verifier := f.service.conceptSourceAuthorityVerifier830G2.(*conceptSourceAuthorityVerifierFake830G2)
	prior := len(verifier.requests)
	draft, err := s.CreateBatchConceptDraftTransferAutomated830G3(f.ctx, f.principal1, f.scope, "transfer-child", transfer)
	require.NoError(t, err)
	_, storedCanonical, err := types.CanonicalBatchConceptCandidateBundle830G3(draft.Manifest)
	require.NoError(t, err)
	require.Equal(t, digestWikiReleaseBytes(candidate), digestWikiReleaseBytes(storedCanonical))
	require.Equal(t, types.WikiReleasePreparationDraft, draft.Status)
	require.Len(t, verifier.requests, prior+1, "transfer must execute original source authority")
	replay, err := s.CreateBatchConceptDraftTransferAutomated830G3(f.ctx, f.principal1, f.scope, draft.ID, transfer)
	require.NoError(t, err)
	require.Equal(t, draft, replay)
	verifier.err = errors.New("source revoked")
	_, err = s.CreateBatchConceptDraftTransferAutomated830G3(f.ctx, f.principal1, f.scope, draft.ID, transfer)
	require.Error(t, err, "current source checks apply even to exact replay")
	verifier.err = nil
	var value map[string]any
	require.NoError(t, json.Unmarshal(transfer, &value))
	value["base"].(map[string]any)["activation_epoch"] = 7
	stale, _ := json.Marshal(value)
	_, err = s.CreateBatchConceptDraftTransferAutomated830G3(f.ctx, f.principal1, f.scope, draft.ID, stale)
	require.Error(t, err)
	policy.Enabled = false
	policy.Digest, _ = SystemAutomationPolicyDigest(policy)
	_, err = s.CreateBatchConceptDraftTransferAutomated830G3(f.ctx, f.principal1, f.scope, draft.ID, transfer)
	require.Error(t, err, "transfer must not bypass policy revocation")
}
