package types

import (
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestSchemaWikiCitationContentAuthorityCanonicalContract(t *testing.T) {
	t.Parallel()
	live := LiveRevisionSourceReceiptV1{
		Contract: "live-revision-source-receipt.v1", RevisionSourceID: strings.Repeat("1", 64),
		TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
		KnowledgeID: "knowledge-terms", EvidenceParseAttemptID: "attempt-2",
		WeKnoraParseAttempt: 2, ResourceID: "resource-terms", FileSHA256: strings.Repeat("2", 64),
		Size: 4096, MimeType: "application/pdf", PageCount: 39,
		ParsedDocumentSHA256: strings.Repeat("3", 64), ParseManifestSHA256: strings.Repeat("4", 64),
		WeKnoraManifestAlgorithm: RevisionManifestAlgorithm,
		WeKnoraManifestDigest:    strings.Repeat("5", 64), WeKnoraChunkCount: 162,
	}
	liveDigest, err := ComputeLiveRevisionSourceReceiptSHA256(live)
	require.NoError(t, err)
	live.SourceReceiptSHA256 = liveDigest
	quote := "本产品提供住院医疗保障"
	quoteHash, _, err := schemaWikiSHA256("schema-wiki-text.v1", map[string]any{"text": quote})
	require.NoError(t, err)
	citation := CitationTargetV1{
		Contract: "citation-target.v1", CitationID: "citation-coverage-12",
		SourceRole: "terms", SpaceID: "space-596-1", EntityVersionID: "596-1",
		KnowledgeID: "knowledge-terms", ChunkID: "chunk-terms-12",
		SourceRevisionID: "revision-2", ParseAttemptID: "attempt-2",
		ParsedDocumentSHA256: strings.Repeat("3", 64), ParseManifestSHA256: strings.Repeat("4", 64),
		PageNumber: 12, LocatorRef: "terms-page-12-block-3",
		BBox:          CitationBBoxV1{CoordinateSystem: "normalized_0_1e6", PageWidth: 1000000, PageHeight: 1000000, X0: 100000, Y0: 200000, X1: 800000, Y1: 900000},
		QuoteSnapshot: quote, QuoteSHA256: quoteHash, ContentSnapshotSHA256: strings.Repeat("8", 64),
		LogicalMemberRef: "field:coverage_scope",
	}
	citationDigest, _, err := schemaWikiHashWithout(citation.Contract, citation, "citation_sha256")
	require.NoError(t, err)
	citation.CitationSHA256 = citationDigest
	authority := SchemaWikiCitationContentAuthorityV1{
		Contract:               "schema-wiki-citation-content-authority.v1",
		TokenKeyID:             "citation-token-key-1",
		ReleaseID:              "release-596-1-v1",
		ActivationEpoch:        7,
		FieldID:                "coverage_scope",
		CitationID:             "citation-coverage-12",
		CandidateSHA256:        strings.Repeat("9", 64),
		RevisionSource:         live,
		CitationSHA256:         citation.CitationSHA256,
		BindingSHA256:          strings.Repeat("a", 64),
		PageNumber:             citation.PageNumber,
		BBox:                   citation.BBox,
		QuoteSHA256:            citation.QuoteSHA256,
		ContentSnapshotSHA256:  citation.ContentSnapshotSHA256,
		CoordinateSpaceVersion: "normalized_0_1e6",
		PageWidth:              1000000, PageHeight: 1000000, RotationDegrees: 0,
		RetentionState: KnowledgeRevisionSourcePinned,
		ExpiresAtUnix:  1786442400,
	}
	digest, err := ComputeSchemaWikiCitationContentAuthoritySHA256(authority)
	require.NoError(t, err)
	authority.AuthoritySHA256 = digest
	require.NoError(t, ValidateSchemaWikiCitationContentAuthorityV1(authority))

	mutated := authority
	mutated.PageNumber = 1
	mutated.AuthoritySHA256, err = ComputeSchemaWikiCitationContentAuthoritySHA256(mutated)
	require.NoError(t, err)
	require.Error(t, ValidateSchemaWikiCitationContentAuthorityAgainst(mutated, authority))
}
