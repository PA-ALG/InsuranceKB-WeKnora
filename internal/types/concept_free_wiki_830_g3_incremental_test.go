package types

import (
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

const (
	actualEpoch9Candidate830G3 = "/private/tmp/g3-final-navigation-epoch9-20260913/candidate.json"
	newIncrementalEntity830G3  = "entity_incremental_published_g3_test"
	newIncrementalVersion830G3 = "entity-version-incremental-published-g3-test-v1"
)

func publishedIncrementalBase830G3(t *testing.T, candidatePath string) ConceptCompileRequest830G2 {
	t.Helper()
	raw, err := os.ReadFile(candidatePath)
	require.NoError(t, err)
	bundle, err := ParseBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	base := bundle.Request.BaseRequest
	base.BaseReleaseID = "release-incremental-g3-test"
	base.BaseActivationEpoch = 9
	base.ExistingDefinitions = bundle.CompileResult.Output.Definitions
	base.ExistingFields = bundle.CompileResult.Output.Fields
	base.ExistingPages = bundle.CompileResult.Output.Pages
	base.EntityVersions = cloneStringMapIncremental830G3(base.EntityVersions)
	base.RequiredFields = cloneRequiredFieldsIncremental830G3(base.RequiredFields)
	base.ExistingEntityVersions = cloneStringMapIncremental830G3(base.EntityVersions)
	return base
}

func addIncrementalEntity830G3(base ConceptCompileRequest830G2) ConceptCompileRequest830G2 {
	base.EntityVersions[newIncrementalEntity830G3] = newIncrementalVersion830G3
	base.RequiredFields[newIncrementalEntity830G3] = []string{"product_name"}
	return base
}

func cloneStringMapIncremental830G3(input map[string]string) map[string]string {
	output := make(map[string]string, len(input))
	for key, value := range input {
		output[key] = value
	}
	return output
}

func cloneRequiredFieldsIncremental830G3(input map[string][]string) map[string][]string {
	output := make(map[string][]string, len(input))
	for key, value := range input {
		output[key] = append([]string(nil), value...)
	}
	return output
}

func TestBatchConceptPublishedG3IncrementalEntity(t *testing.T) {
	base := publishedIncrementalBase830G3(t, batchConceptFixture830G3)
	require.Len(t, base.ExistingFields, 342)
	kind, err := batchConceptBaseKind830G3(base)
	require.NoError(t, err)
	require.Equal(t, batchConceptBasePublishedG3, kind)

	incremental := addIncrementalEntity830G3(base)
	kind, err = batchConceptBaseKind830G3(incremental)
	require.NoError(t, err)
	require.Equal(t, batchConceptBasePublishedG3, kind)
	require.NotContains(t, incremental.ExistingEntityVersions, newIncrementalEntity830G3)
}

func TestBatchConceptPublishedG3IncrementalRechecksOldFields(t *testing.T) {
	base := addIncrementalEntity830G3(
		publishedIncrementalBase830G3(t, batchConceptFixture830G3),
	)
	base.ExistingFields = base.ExistingFields[:len(base.ExistingFields)-1]

	_, err := batchConceptBaseKind830G3(base)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
}

func TestBatchConceptPublishedG3IncrementalRechecksOldVersions(t *testing.T) {
	base := addIncrementalEntity830G3(
		publishedIncrementalBase830G3(t, batchConceptFixture830G3),
	)
	for entityID := range base.ExistingEntityVersions {
		base.EntityVersions[entityID] = "entity-version-drift-test-v1"
		break
	}

	_, err := batchConceptBaseKind830G3(base)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
}

func TestBatchConceptPublishedG3IncrementalRejectsNewEntityAsExisting(t *testing.T) {
	base := addIncrementalEntity830G3(
		publishedIncrementalBase830G3(t, batchConceptFixture830G3),
	)
	base.ExistingEntityVersions[newIncrementalEntity830G3] = newIncrementalVersion830G3

	_, err := batchConceptBaseKind830G3(base)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
}

func TestBatchConceptActualEpoch9IncrementalEntity(t *testing.T) {
	candidatePath := os.Getenv("G3_INCREMENTAL_PARENT_CANDIDATE")
	if candidatePath == "" {
		candidatePath = actualEpoch9Candidate830G3
	}
	if _, err := os.Stat(candidatePath); err != nil {
		t.Skipf("actual epoch9 candidate unavailable: %s", candidatePath)
	}
	base := addIncrementalEntity830G3(publishedIncrementalBase830G3(t, candidatePath))
	require.Len(t, base.ExistingFields, 493)

	kind, err := batchConceptBaseKind830G3(base)
	require.NoError(t, err)
	require.Equal(t, batchConceptBasePublishedG3, kind)
}
