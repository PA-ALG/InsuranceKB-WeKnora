package service

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func cfg42LegacyDigestFixture(t *testing.T) (*ConceptSourceAuthorityService830G2, ConceptCitationAuthorityRequest830G2, *types.SchemaWikiCitationContentAuthorityV1) {
	t.Helper()
	bridge, request := cfg42AuthorityFixture(t)
	repo := bridge.revisions.(*conceptKnowledgeStub830G2)
	// These distinct digest domains reproduce the published legacy terms case.
	repo.source.ManifestDigest = "f2190b125469819ea0d97603c71f4fb19e4a92fa09117582b4d581947a0de414"
	var err error
	repo.source.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(*repo.source)
	require.NoError(t, err)
	request.Evidence.ParseHash = "790a5092a98a929093312a090a9a1bc7aec1cbba22af22c113184350eae442f5"
	request.SourceBlock.ConceptSourceIdentity830G2 = request.Evidence.ConceptSourceIdentity830G2
	request.Bundle = &types.ConceptCandidateBundle830G2{}
	proof := &types.SchemaWikiCitationContentAuthorityV1{
		RevisionSource: types.LiveRevisionSourceReceiptV1{
			RevisionSourceID:    request.Evidence.RevisionID,
			ParseManifestSHA256: request.Evidence.ParseHash,
		},
		PageNumber: request.Evidence.PageNumber,
		BBox:       types.CitationBBoxV1{X0: 1, Y0: 2, X1: 3, Y1: 4},
	}
	canonical, err := canonicalJSON830G2(request.Evidence)
	require.NoError(t, err)
	key := request.MemberID + "\x00" + testSHA256Bytes830G2(canonical)
	// The seam supplies the result of the separately tested immutable C5 replay.
	bridge.legacyProofResolver = func(context.Context, types.WikiReleaseScope, types.ConceptCandidateBundle830G2) (map[string]conceptLegacyProof830G2, error) {
		return map[string]conceptLegacyProof830G2{key: {authority: proof}}, nil
	}
	return bridge, request, proof
}

func TestCFG42LegacyDistinctDigestsIssueAndReopen(t *testing.T) {
	bridge, request, proof := cfg42LegacyDigestFixture(t)
	repo := bridge.revisions.(*conceptKnowledgeStub830G2)
	originalSource := *repo.source
	originalEvidence := request.Evidence
	require.NotEqual(t, repo.source.ManifestDigest, request.Evidence.ParseHash)
	require.Equal(t, proof.RevisionSource.ParseManifestSHA256, request.Evidence.ParseHash)

	authority, err := bridge.IssueConceptCitationAuthority830G2(context.Background(), request)
	require.NoError(t, err)
	require.Equal(t, request.Evidence.ParseHash, authority.Source.ParseHash)
	require.Equal(t, repo.source.BindingDigest, authority.RevisionSource.BindingDigest)
	require.Nil(t, authority.SourceLocator, "legacy authority must retain the original C5 coordinates")
	contents, err := bridge.ReadConceptCitationByOpaqueToken830G2(context.Background(), request.Scope, authority.OpaqueToken, request)
	require.NoError(t, err)
	require.Equal(t, []byte("pdf"), contents)
	require.Equal(t, originalSource, *repo.source)
	require.Equal(t, originalEvidence, request.Evidence)
	require.Zero(t, bridge.docreader.(*nativeIndexDocReader830G2).calls)
}

func TestCFG42LegacyDigestRepairPreservesProofAndSourceGates(t *testing.T) {
	for _, name := range []string{"proof digest", "evidence digest", "member", "binding", "resource", "proof page"} {
		t.Run(name, func(t *testing.T) {
			bridge, request, proof := cfg42LegacyDigestFixture(t)
			repo := bridge.revisions.(*conceptKnowledgeStub830G2)
			authority, err := bridge.IssueConceptCitationAuthority830G2(context.Background(), request)
			require.NoError(t, err)
			switch name {
			case "proof digest":
				proof.RevisionSource.ParseManifestSHA256 = repo.source.ManifestDigest
			case "evidence digest":
				request.Evidence.ParseHash = repo.source.ManifestDigest
			case "member":
				request.MemberID = "unrelated-member"
			case "binding":
				repo.source.BindingDigest = testSHA830G2("tampered binding")
			case "resource":
				repo.resource.ID = "unrelated-resource"
			case "proof page":
				proof.PageNumber++
			}
			_, err = bridge.IssueConceptCitationAuthority830G2(context.Background(), request)
			require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
			_, err = bridge.ReadConceptCitationByOpaqueToken830G2(context.Background(), request.Scope, authority.OpaqueToken, request)
			require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
		})
	}
}

func TestCFG42LegacyDigestRepairDoesNotRelaxNativeDigests(t *testing.T) {
	for _, mismatch := range []string{"revision", "source"} {
		t.Run(mismatch, func(t *testing.T) {
			bridge, doc, scope, evidence, block := nativeIndexFixture830G2(t)
			_, _, err := bridge.verifyEvidence(context.Background(), scope, evidence, &block)
			require.NoError(t, err, "native fixture must pass before the digest mutation")
			repo := bridge.revisions.(*conceptKnowledgeStub830G2)
			if mismatch == "revision" {
				evidence.ParseHash = testSHA830G2("historical evidence manifest")
				block.ConceptSourceIdentity830G2 = evidence.ConceptSourceIdentity830G2
			} else {
				repo.source.ManifestDigest = testSHA830G2("other native manifest")
				repo.source.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(*repo.source)
				require.NoError(t, err)
			}
			_, _, err = bridge.verifyEvidence(context.Background(), scope, evidence, &block)
			require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
			require.Equal(t, 1, doc.calls, "mismatch must fail before another native capture")
		})
	}
}
