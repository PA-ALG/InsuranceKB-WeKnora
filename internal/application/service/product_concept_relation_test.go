package service

import (
	"bytes"
	"compress/gzip"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"io"
	"os"
	"testing"
)

func TestProductConceptRelationReadNavigation(t *testing.T) {
	raw, err := os.ReadFile("../../types/testdata/product_concept_relation_candidate.json.gz")
	require.NoError(t, err)
	reader, err := gzip.NewReader(bytes.NewReader(raw))
	require.NoError(t, err)
	wire, err := io.ReadAll(reader)
	require.NoError(t, err)
	require.NoError(t, reader.Close())
	bundle, _, err := types.CanonicalBatchConceptCandidateBundle830G3(wire)
	require.NoError(t, err)
	var relation, concept, overview types.ConceptPageMember830G2
	var relationPage types.ConceptFreeWikiPage830G2
	for _, page := range bundle.CompileResult.Output.Pages {
		if page.BusinessRelation != nil {
			relationPage = page
		}
	}
	relationID, err := relationPage.FreeWikiPageID()
	require.NoError(t, err)
	for _, member := range bundle.PageManifest.Members {
		if member.MemberID == relationID {
			relation = member
		}
		if member.MemberID == relationPage.BusinessRelation.ObjectConceptID {
			concept = member
		}
		if member.OwnerID == relationPage.EntityID && member.Kind == "entity_overview" {
			overview = member
		}
	}
	projected := types.ConceptCandidateBundle830G2{CompileResult: bundle.CompileResult,
		PageManifest: types.ConceptPageManifest830G2{Members: bundle.PageManifest.Members}}
	assert.Contains(t, conceptRelatedMembers830G2(projected, concept), relation)
	require.Contains(t, conceptRelatedMembers830G2(projected, relation), concept)
	related, err := batchConceptOverviewRelatedMembers830G3(bundle, overview)
	require.NoError(t, err)
	require.Contains(t, related, relation)
}
