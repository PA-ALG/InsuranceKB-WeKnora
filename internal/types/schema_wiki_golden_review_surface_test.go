package types

import (
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestSchema67GoldenEvaluationReviewBundleCrossLanguageVector(t *testing.T) {
	t.Parallel()
	raw, err := os.ReadFile("../../harness/tests/fixtures/schema67_golden_evaluation_bundle_596_1.json")
	require.NoError(t, err)
	bundle, err := ParseSchema67GoldenEvaluationReviewBundleV1(raw)
	require.NoError(t, err)
	require.Equal(t, bundle.QualityGateReceipt.ReceiptSHA256, bundle.EvaluationID)
	require.Len(t, bundle.PrivateDossier.FieldDecisions, 67)
	require.Equal(t, bundle.PublicAggregate.Metrics, bundle.PrivateDossier.Metrics)

	mutated := bundle
	mutated.PrivateDossier.FieldDecisions = append(
		[]Schema67GoldenFieldDecisionV1(nil), bundle.PrivateDossier.FieldDecisions...,
	)
	mutated.PrivateDossier.FieldDecisions[0].FieldID = "foreign-field"
	mutated.PrivateDossier.FieldDecisions[0].DecisionSHA256 = ""
	mutated.PrivateDossier.FieldDecisions[0].DecisionSHA256, _, err = schemaWikiHashWithout(
		"schema67-golden-field-decision.v1",
		mutated.PrivateDossier.FieldDecisions[0],
		"decision_sha256",
	)
	require.NoError(t, err)
	mutated.PrivateDossier.DossierSHA256 = ""
	mutated.PrivateDossier.DossierSHA256, _, err = schemaWikiHashWithout(
		mutated.PrivateDossier.Contract, mutated.PrivateDossier, "dossier_sha256",
	)
	require.NoError(t, err)
	mutated.QualityGateReceipt.OrderedFieldDecisionSHA256s = append(
		[]string(nil), bundle.QualityGateReceipt.OrderedFieldDecisionSHA256s...,
	)
	mutated.QualityGateReceipt.OrderedFieldDecisionSHA256s[0] =
		mutated.PrivateDossier.FieldDecisions[0].DecisionSHA256
	mutated.QualityGateReceipt.PrivateDossierSHA256 = mutated.PrivateDossier.DossierSHA256
	mutated.QualityGateReceipt.ReceiptSHA256 = ""
	mutated.QualityGateReceipt.ReceiptSHA256, _, err = schemaWikiHashWithout(
		mutated.QualityGateReceipt.Contract,
		mutated.QualityGateReceipt,
		"receipt_sha256",
	)
	require.NoError(t, err)
	mutated.EvaluationID = mutated.QualityGateReceipt.ReceiptSHA256
	mutated.EvaluationBundleSHA256 = ""
	mutated.EvaluationBundleSHA256, _, err = schemaWikiHashWithout(
		mutated.Contract, mutated, "evaluation_bundle_sha256",
	)
	require.NoError(t, err)
	require.ErrorIs(
		t, ValidateSchema67GoldenEvaluationReviewBundleV1(mutated), ErrSchemaWikiContractInvalid,
	)
}
