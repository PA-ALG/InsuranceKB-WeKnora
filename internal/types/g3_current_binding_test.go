package types

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestCurrentBatchBindingIDsFollowResolutionInsteadOfPublishedMembership(t *testing.T) {
	raw, err := os.ReadFile("../../harness/tests/fixtures/batch_concept_compile_830_g3/platform-incremental-candidate.json")
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(raw, &bundle))
	before, err := json.Marshal(bundle.Request)
	require.NoError(t, err)
	current, err := CurrentBatchBindingIDs830G3(bundle.Request)
	require.NoError(t, err)
	require.Len(t, current, 1)
	parentCurrent, parentCarried := 0, 0
	for _, binding := range bundle.Request.PublishedBase.EntityBindings {
		if current[binding.EntityID] {
			parentCurrent++
		} else {
			parentCarried++
		}
	}
	require.Equal(t, 1, parentCurrent, "the existing entity refreshed by this fixture remains current work")
	require.Greater(t, parentCarried, 0, "unaffected parent bindings remain carried")
	after, err := json.Marshal(bundle.Request)
	require.NoError(t, err)
	require.Equal(t, before, after)
	// A current resolution may MATCH/refresh an existing entity. Historical
	// membership is never itself a reason to suppress that current work.
	bundle.Request.BaseRequest.ExistingEntityVersions = map[string]string{}
	for _, binding := range bundle.Request.EntityBindings {
		bundle.Request.BaseRequest.ExistingEntityVersions[binding.EntityID] = binding.EntityVersion
	}
	again, err := CurrentBatchBindingIDs830G3(bundle.Request)
	require.NoError(t, err)
	require.Equal(t, current, again)
	// Corrupting a current ref cannot turn it into silently skipped history.
	for i := range bundle.Request.EntityBindings {
		if current[bundle.Request.EntityBindings[i].EntityID] {
			bundle.Request.EntityBindings[i].ResolutionRefs[0].ProposalRef = "missing-proposal"
			break
		}
	}
	_, err = CurrentBatchBindingIDs830G3(bundle.Request)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
}
