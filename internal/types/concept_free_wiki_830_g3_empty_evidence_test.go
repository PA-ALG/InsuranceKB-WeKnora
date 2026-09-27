package types

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestExpectedEntityDecision830G3PreservesEmptyEvidenceArrays(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(raw, &bundle))
	typed, err := decodeResolutionInputs830G3(bundle.Request.ResolutionInputs, bundle.Request.Resolution)
	require.NoError(t, err)
	entity := typed.Proposals.Proposals[0].Entities[0]
	classification, err := expectedClassification830G3(entity, typed.Policy, bundle.Request.Catalog)
	require.NoError(t, err)
	for _, tc := range []struct {
		name             string
		nameIDs, codeIDs []string
	}{
		{"missing name", []string{}, []string{"code-evidence"}},
		{"missing code", []string{"name-evidence"}, []string{}},
		{"both absent", []string{}, []string{}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			row := resolutionRow830G3{Entity: entity, Reasons: map[string]bool{"VERSION_UNRESOLVED": true}, Classification: classification, MultiName: tc.nameIDs, MultiCode: tc.codeIDs}
			decision, err := expectedEntityDecision830G3(row, typed.Existing, typed.Policy)
			require.NoError(t, err)
			require.Equal(t, "NEEDS_CONFIRM", decision.Disposition)
			require.Equal(t, tc.nameIDs, decision.MultiIdentityNameEvidenceIDs)
			require.Equal(t, tc.codeIDs, decision.MultiIdentityCodeEvidenceIDs)
			// The closed wire contract and Python canonical hash use [], never null.
			wire, err := json.Marshal(decision)
			require.NoError(t, err)
			var roundTrip EntityDecision830G3
			require.NoError(t, json.Unmarshal(wire, &roundTrip))
			require.NotNil(t, roundTrip.MultiIdentityNameEvidenceIDs)
			require.NotNil(t, roundTrip.MultiIdentityCodeEvidenceIDs)
			require.True(t, hashEqualWithout830G3("entity-decision.830.g3.v1", roundTrip, "decision_sha256", decision.DecisionSHA256))
		})
	}
}

func TestBatchConceptCandidate830G3PrivateActualReadback(t *testing.T) {
	path := os.Getenv("G3_ACTUAL_CANDIDATE_PATH")
	if path == "" {
		t.Skip("private actual Candidate is opt-in; never committed")
	}
	raw, err := os.ReadFile(path)
	require.NoError(t, err)
	bundle, _, err := CanonicalBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	_, err = bundle.SnapshotMembers()
	require.NoError(t, err)
}
