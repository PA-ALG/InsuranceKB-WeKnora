package types

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestSchemaWikiGoldenReviewerDossierV2CrossLanguageVector(t *testing.T) {
	t.Parallel()
	raw, err := os.ReadFile(
		"../../harness/tests/fixtures/schema67_golden_reviewer_dossier_v2_596_1.json",
	)
	require.NoError(t, err)
	dossier, err := ParseSchemaWikiGoldenQualityDossierV2(raw)
	require.NoError(t, err)
	require.Equal(t, "schema-wiki-golden-quality-dossier.v2", dossier.Version)
	require.Len(t, dossier.ReviewSuccessor.OrderedFields, 67)
	require.Equal(t, "linyao", dossier.ReviewSuccessor.HumanReviewLayer.ReviewedBy)
	require.Equal(t, "VERIFIED", dossier.ReviewSuccessor.HumanReviewLayer.ReceiptStatus)

	var payload map[string]any
	require.NoError(t, json.Unmarshal(raw, &payload))
	payload["foreign_authority"] = "caller"
	forged, err := json.Marshal(payload)
	require.NoError(t, err)
	_, err = ParseSchemaWikiGoldenQualityDossierV2(forged)
	require.ErrorIs(t, err, ErrSchemaWikiContractInvalid)

	var equivalent any
	require.NoError(t, json.Unmarshal(raw, &equivalent))
	spaced, err := json.MarshalIndent(equivalent, "", "  ")
	require.NoError(t, err)
	require.True(t, json.Valid(spaced))
	_, err = ParseSchemaWikiGoldenQualityDossierV2(spaced)
	require.ErrorIs(t, err, ErrSchemaWikiContractInvalid)
}

func TestSchemaWikiGoldenReviewerMetadataRejectsResidualOrSelfRehash(t *testing.T) {
	raw, err := os.ReadFile(
		"../../harness/tests/fixtures/schema67_golden_reviewer_dossier_v2_596_1.json",
	)
	require.NoError(t, err)
	dossier, err := ParseSchemaWikiGoldenQualityDossierV2(raw)
	require.NoError(t, err)

	forged := dossier.ReviewSuccessor
	forged.OrderedFields = append([]Schema67GoldenReviewFieldMetadataV1(nil), forged.OrderedFields...)
	forged.OrderedFields[0].ReviewStatus = "PENDING_RESIDUAL"
	forged.OrderedFields[0].ReasonCodes = []string{"TRI_STATE_CONFLICT"}
	forged.OrderedFields[0].FieldMetadataSHA256, _, err = schemaWikiHashWithout(
		"schema67-golden-review-field-metadata.v1",
		forged.OrderedFields[0],
		"field_metadata_sha256",
	)
	require.NoError(t, err)
	forged.MetadataSHA256, _, err = schemaWikiHashWithout(
		forged.Contract, forged, "metadata_sha256",
	)
	require.NoError(t, err)
	require.ErrorIs(
		t, ValidateSchema67GoldenReviewSuccessorMetadataV1(forged, Schema67GoldenEvaluationReviewBundleV1{}, Schema67CandidateEvidenceAuthorityV1{}),
		ErrSchemaWikiContractInvalid,
	)
}
