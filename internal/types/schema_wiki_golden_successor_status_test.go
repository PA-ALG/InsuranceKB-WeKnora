package types

import (
	"bytes"
	"encoding/json"
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

func loadSchemaWikiGoldenSuccessorStatusVector(t *testing.T) []byte {
	t.Helper()
	raw, err := os.ReadFile("testdata/schema_wiki_golden_successor_status_596_1.json")
	require.NoError(t, err)
	return raw
}

func TestSchemaWikiGoldenSuccessorStatusVectorIsClosedAndCanonical(t *testing.T) {
	t.Parallel()
	raw := loadSchemaWikiGoldenSuccessorStatusVector(t)
	status, err := ParseSchemaWikiGoldenSuccessorStatusV1(raw)
	require.NoError(t, err)
	require.Equal(t, "linyao", status.ReviewedBy)
	require.Nil(t, status.ReviewedAt)
	require.Equal(t, 51, status.ClosedCount)
	require.Equal(t, 16, status.ResidualCount)
	require.Len(t, status.ResidualFieldIDs, 16)

	var object map[string]any
	require.NoError(t, json.Unmarshal(raw, &object))
	object["foreign_authority"] = "caller"
	foreign, err := json.Marshal(object)
	require.NoError(t, err)
	_, err = ParseSchemaWikiGoldenSuccessorStatusV1(foreign)
	require.ErrorIs(t, err, ErrSchemaWikiContractInvalid)

	var equivalent any
	require.NoError(t, json.Unmarshal(raw, &equivalent))
	spaced, err := json.MarshalIndent(equivalent, "", "  ")
	require.NoError(t, err)
	_, err = ParseSchemaWikiGoldenSuccessorStatusV1(spaced)
	require.ErrorIs(t, err, ErrSchemaWikiContractInvalid)

	_, err = ParseSchemaWikiGoldenSuccessorStatusV1(append(bytes.TrimSpace(raw), []byte(` {}`)...))
	require.ErrorIs(t, err, ErrSchemaWikiContractInvalid)
}

func TestSchemaWikiGoldenSuccessorStatusRejectsEveryAuthorityDrift(t *testing.T) {
	raw := loadSchemaWikiGoldenSuccessorStatusVector(t)
	status, err := ParseSchemaWikiGoldenSuccessorStatusV1(raw)
	require.NoError(t, err)

	mutations := map[string]func(*SchemaWikiGoldenSuccessorStatusV1){
		"golden hash":  func(v *SchemaWikiGoldenSuccessorStatusV1) { v.GoldenSetSHA256 = string(bytes.Repeat([]byte{'f'}, 64)) },
		"mapping hash": func(v *SchemaWikiGoldenSuccessorStatusV1) { v.MappingSHA256 = string(bytes.Repeat([]byte{'e'}, 64)) },
		"successor hash": func(v *SchemaWikiGoldenSuccessorStatusV1) {
			v.SuccessorFileSHA256 = string(bytes.Repeat([]byte{'d'}, 64))
		},
		"attestation hash": func(v *SchemaWikiGoldenSuccessorStatusV1) {
			v.AttestationSHA256 = string(bytes.Repeat([]byte{'c'}, 64))
		},
		"source status":  func(v *SchemaWikiGoldenSuccessorStatusV1) { v.SourceReviewStatus = "PENDING" },
		"reviewer":       func(v *SchemaWikiGoldenSuccessorStatusV1) { v.ReviewedBy = "caller" },
		"annotator":      func(v *SchemaWikiGoldenSuccessorStatusV1) { v.AnnotatorModelID = "caller-model" },
		"mapping status": func(v *SchemaWikiGoldenSuccessorStatusV1) { v.Schema67MappingStatus = "COMPLETE" },
		"closed count":   func(v *SchemaWikiGoldenSuccessorStatusV1) { v.ClosedCount = 52 },
		"residual count": func(v *SchemaWikiGoldenSuccessorStatusV1) { v.ResidualCount = 15 },
		"residual order": func(v *SchemaWikiGoldenSuccessorStatusV1) {
			v.ResidualFieldIDs[0], v.ResidualFieldIDs[1] = v.ResidualFieldIDs[1], v.ResidualFieldIDs[0]
		},
		"admission status":  func(v *SchemaWikiGoldenSuccessorStatusV1) { v.GoldenAdmissionStatus = "PASS" },
		"receipt status":    func(v *SchemaWikiGoldenSuccessorStatusV1) { v.ReceiptStatus = "VERIFIED" },
		"ready to sign":     func(v *SchemaWikiGoldenSuccessorStatusV1) { v.ReadyToSignStatus = "SIGNED" },
		"review time claim": func(v *SchemaWikiGoldenSuccessorStatusV1) { now := "2026-08-11T11:21:07Z"; v.ReviewedAt = &now },
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			forged := status
			forged.ResidualFieldIDs = append([]string(nil), status.ResidualFieldIDs...)
			mutate(&forged)
			forged.StatusSHA256, err = ComputeSchemaWikiGoldenSuccessorStatusSHA256(forged)
			require.NoError(t, err)
			require.ErrorIs(t, ValidateSchemaWikiGoldenSuccessorStatusV1(forged), ErrSchemaWikiContractInvalid)
		})
	}
}
