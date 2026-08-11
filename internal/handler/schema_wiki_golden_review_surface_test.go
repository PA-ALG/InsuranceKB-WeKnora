package handler

import (
	"encoding/json"
	"net/http"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func TestSchemaWikiPreparationGoldenSummaryIsClosedAndPublic(t *testing.T) {
	t.Parallel()
	spy := &schemaWikiHTTPServiceSpy{goldenSummary: &types.SchemaWikiGoldenQualitySummaryV1{
		Version: "schema-wiki-golden-quality-summary.v1",
		PublicAggregate: types.Schema67GoldenPublicAggregateV1{
			Contract: "schema67-golden-public-aggregate.v1", Status: "PASS",
		},
		ServingEffect: "NONE",
	}}
	h := NewSchemaWikiHandler(nil, spy)
	c, recorder := schemaWikiScopeContext(t, gin.Params{
		{Key: "kb_id", Value: "wiki-596-1"},
		{Key: "space_id", Value: "space-596-1"},
		{Key: "raw_kb_id", Value: "raw-596-1"},
		{Key: "preparation_id", Value: "preparation-596-1"},
		{Key: "evaluation_id", Value: "evaluation-596-1"},
	})
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "reviewer-1"}
	c.Request = c.Request.WithContext(types.WithPrincipal(c.Request.Context(), principal))
	c.Set(types.PrincipalContextKey.String(), principal)

	h.ReadPreparationGoldenQualitySummary(c)

	require.Equal(t, http.StatusOK, recorder.Code)
	var response struct {
		Success bool                   `json:"success"`
		Data    map[string]interface{} `json:"data"`
	}
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &response))
	require.True(t, response.Success)
	require.Equal(t, "schema-wiki-golden-quality-summary.v1", response.Data["version"])
	require.Equal(t, "NONE", response.Data["serving_effect"])
	for _, privateKey := range []string{
		"field_decisions", "canonical_value", "candidate_value", "quote_snapshot",
	} {
		require.NotContains(t, recorder.Body.String(), privateKey)
	}
	require.Equal(t, 1, spy.goldenSummaryCalls)
	require.Zero(t, spy.goldenPrivateCalls)
}

func TestSchemaWikiPreparationGoldenPrivateDossierUsesPreparationIdentityOnly(t *testing.T) {
	t.Parallel()
	spy := &schemaWikiHTTPServiceSpy{goldenPrivate: &types.SchemaWikiGoldenQualityDossierV2{
		Version: "schema-wiki-golden-quality-dossier.v2",
		PrivateDossier: types.Schema67GoldenPrivateDossierV1{
			Contract: "schema67-golden-private-dossier.v1", Status: "PASS",
		},
		ServingEffect: "NONE",
	}}
	h := NewSchemaWikiHandler(nil, spy)
	c, recorder := schemaWikiScopeContext(t, gin.Params{
		{Key: "kb_id", Value: "wiki-596-1"},
		{Key: "space_id", Value: "space-596-1"},
		{Key: "raw_kb_id", Value: "raw-596-1"},
		{Key: "preparation_id", Value: "preparation-596-1"},
		{Key: "evaluation_id", Value: "evaluation-596-1"},
	})
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "named-reviewer-1"}
	c.Request = c.Request.WithContext(types.WithPrincipal(c.Request.Context(), principal))
	c.Set(types.PrincipalContextKey.String(), principal)

	h.ReadPreparationGoldenQualityDossier(c)

	require.Equal(t, http.StatusOK, recorder.Code)
	require.Contains(t, recorder.Body.String(), "schema-wiki-golden-quality-dossier.v2")
	var response struct {
		Success bool                   `json:"success"`
		Data    map[string]interface{} `json:"data"`
	}
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &response))
	require.ElementsMatch(t, []string{
		"version", "preparation_id", "evaluation_id",
		"quality_gate_receipt_sha256", "private_dossier", "review_successor",
		"evaluation_bundle_sha256", "serving_effect",
	}, func() []string {
		keys := make([]string, 0, len(response.Data))
		for key := range response.Data {
			keys = append(keys, key)
		}
		return keys
	}())
	require.NotContains(t, recorder.Body.String(), "release_id")
	require.NotContains(t, recorder.Body.String(), "active")
	for _, forbidden := range []string{"approve", "publish", "activate", "create_draft"} {
		require.NotContains(t, recorder.Body.String(), forbidden)
	}
	require.Equal(t, 1, spy.goldenPrivateCalls)
}

func TestSchemaWikiPreparationGoldenEvidencePreviewAcceptsOnlyPathIdentities(t *testing.T) {
	t.Parallel()
	spy := &schemaWikiHTTPServiceSpy{goldenPreview: &types.SchemaWikiGoldenEvidencePreviewAuthorityV1{
		Contract:      "schema-wiki-golden-evidence-preview-authority.v1",
		PreparationID: "preparation-596-1",
		EvaluationID:  "evaluation-596-1",
		FieldID:       "product_code",
		EvidenceID:    "evidence-596-1",
		OpaqueToken:   "opaque-review-token",
	}}
	h := NewSchemaWikiHandler(nil, spy)
	c, recorder := schemaWikiScopeContext(t, gin.Params{
		{Key: "kb_id", Value: "wiki-596-1"},
		{Key: "space_id", Value: "space-596-1"},
		{Key: "raw_kb_id", Value: "raw-596-1"},
		{Key: "preparation_id", Value: "preparation-596-1"},
		{Key: "evaluation_id", Value: "evaluation-596-1"},
		{Key: "field_id", Value: "product_code"},
		{Key: "evidence_id", Value: "evidence-596-1"},
	})
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "named-reviewer-1"}
	c.Request = c.Request.WithContext(types.WithPrincipal(c.Request.Context(), principal))
	c.Set(types.PrincipalContextKey.String(), principal)

	h.PreviewPreparationGoldenEvidence(c)

	require.Equal(t, http.StatusOK, recorder.Code)
	require.Contains(t, recorder.Body.String(), "opaque-review-token")
	require.NotContains(t, recorder.Body.String(), "quote_snapshot")
	require.NotContains(t, recorder.Body.String(), "file_path")
	require.Equal(t, 1, spy.goldenPreviewCalls)
}

func TestSchemaWikiGoldenSuccessorStatusResponseIsClosedNonServingMetadata(t *testing.T) {
	t.Parallel()
	status := &types.SchemaWikiGoldenSuccessorStatusV1{
		Version:  "schema-wiki-golden-successor-status.v1",
		Contract: "schema-wiki-golden-successor-status.v1",
		TenantID: 10003, SpaceID: "space-596-1", RawKBID: "raw-kb-596-1",
		WikiKBID: "wiki-kb-596-1", ProductVersionID: "596-1",
		SchemaPackID: "medical-schema67.v1", SourceReviewStatus: "COMPLETED",
		ReviewedBy: "linyao", AnnotatorModelID: "claude-fable-5",
		Schema67MappingStatus: "COMPLETE_67",
		ClosedCount:           67, ResidualCount: 0,
		GoldenAdmissionStatus: "BLOCKED_RECEIPT_UNVERIFIED",
		ReceiptStatus:         "UNVERIFIED",
		ReadyToSignStatus:     "READY_TO_SIGN",
	}
	spy := &schemaWikiHTTPServiceSpy{goldenSuccessor: status}
	h := NewSchemaWikiHandler(nil, spy)
	c, recorder := schemaWikiScopeContext(t, gin.Params{
		{Key: "kb_id", Value: "wiki-kb-596-1"},
		{Key: "space_id", Value: "space-596-1"},
		{Key: "raw_kb_id", Value: "raw-kb-596-1"},
	})
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "named-reviewer-1"}
	c.Request = c.Request.WithContext(types.WithPrincipal(c.Request.Context(), principal))
	c.Set(types.PrincipalContextKey.String(), principal)

	h.ReadGoldenSuccessorStatus(c)

	require.Equal(t, http.StatusOK, recorder.Code)
	var response struct {
		Success bool                   `json:"success"`
		Data    map[string]interface{} `json:"data"`
	}
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &response))
	require.True(t, response.Success)
	require.ElementsMatch(t, []string{
		"version", "contract", "tenant_id", "space_id", "raw_kb_id", "wiki_kb_id",
		"product_version_id", "schema_pack_id", "golden_set_sha256", "mapping_sha256",
		"successor_file_sha256", "attestation_sha256", "source_review_status",
		"reviewed_by", "annotator_model_id", "reviewed_at", "attestor_id", "attested_at",
		"schema67_mapping_status", "closed_count", "residual_count", "residual_field_ids",
		"golden_admission_status", "receipt_status", "ready_to_sign_status", "status_sha256",
	}, func() []string {
		keys := make([]string, 0, len(response.Data))
		for key := range response.Data {
			keys = append(keys, key)
		}
		return keys
	}())
	for _, forbidden := range []string{
		"field_value", "evidence", "quality_pass", "signature", "approve", "publish",
		"activate", "preparation_id", "release_id",
	} {
		require.NotContains(t, recorder.Body.String(), forbidden)
	}
	require.Equal(t, 1, spy.goldenSuccessorCalls)
}
