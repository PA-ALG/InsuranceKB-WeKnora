package service

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestIncrementalSourceGateSelectsOnlyCurrentResolutionMaterials(t *testing.T) {
	raw, err := os.ReadFile("../../../harness/tests/fixtures/batch_concept_compile_830_g3/platform-incremental-candidate.json")
	require.NoError(t, err)
	var bundle types.BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(raw, &bundle))
	before, err := json.Marshal(bundle.Request)
	require.NoError(t, err)
	got, err := selectedBatchCorpusMaterialIDs830G3(bundle.Request)
	require.NoError(t, err)
	expected := map[string]struct{}{}
	for _, entry := range bundle.Request.ResolutionInputs.Corpus.Entries {
		expected[entry.MaterialID] = struct{}{}
	}
	require.Equal(t, expected, got, "the actual source gate must not demand carried parent materials in the current corpus")
	after, err := json.Marshal(bundle.Request)
	require.NoError(t, err)
	require.Equal(t, before, after)
}

func TestIncrementalSourceGateRejectsMissingCurrentCorpus(t *testing.T) {
	raw, err := os.ReadFile("../../../harness/tests/fixtures/batch_concept_compile_830_g3/platform-incremental-candidate.json")
	require.NoError(t, err)
	var bundle types.BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(raw, &bundle))
	bundle.Request.ResolutionInputs.Corpus.Entries = nil
	_, err = selectedBatchCorpusMaterialIDs830G3(bundle.Request)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
}
