package types

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestPlatformIncrementalCandidateCrossLanguageVector830G3(t *testing.T) {
	raw, err := os.ReadFile("../../harness/tests/fixtures/batch_concept_compile_830_g3/platform-incremental-candidate.json")
	require.NoError(t, err)
	digest := sha256.Sum256(raw)
	require.Equal(t, "183975c8374ef31b4a1c87b5398e73a839d30874c6d58cd8e7d9cd4f2f14a246", hex.EncodeToString(digest[:]))
	child, canonical, err := CanonicalBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	require.True(t, bytes.Equal(raw, canonical))
	require.NotNil(t, child.Request.PublishedBase)
	require.Len(t, child.Request.RefreshFields, 1)
	typed, err := decodeResolutionInputs830G3(child.Request.ResolutionInputs, child.Request.Resolution)
	require.NoError(t, err)
	require.Len(t, typed.Proposals.Proposals, 1)
	require.Greater(t, len(child.Request.EntityBindings), 1)

	parent := fixtureBundleForIncrementalTest830G3(t)
	published := child.Request.PublishedBase
	require.NoError(t, ValidateBatchPublishedBaseHistory830G3(
		parent, child, published.ReleaseID, published.ActivationEpoch, published.ManifestDigest,
	))
}

func fixtureBundleForIncrementalTest830G3(t *testing.T) BatchConceptCandidateBundle830G3 {
	t.Helper()
	raw, err := os.ReadFile("../../harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json")
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(raw, &bundle))
	return bundle
}

func TestPublishedBaseBinding830G3ValidatesCanonicalIdentity(t *testing.T) {
	bundle := fixtureBundleForIncrementalTest830G3(t)
	var err error
	binding := PublishedBaseBinding830G3{
		Contract:        "published-base-binding.830.g3.v1",
		ReleaseID:       "release-platform-parent",
		ActivationEpoch: 6,
		CandidateSHA256: bundle.CandidateHash,
		ManifestDigest:  strings.Repeat("a", 64),
		EntityBindings:  bundle.Request.EntityBindings,
	}
	binding.BindingSHA256, err = batchConceptHashWithout830G3(
		binding.Contract, binding, "binding_sha256",
	)
	require.NoError(t, err)
	require.NoError(t, validatePublishedBaseBinding830G3(&binding))

	changed := binding
	changed.EntityBindings = changed.EntityBindings[:len(changed.EntityBindings)-1]
	require.ErrorIs(t, validatePublishedBaseBinding830G3(&changed), ErrConceptCandidateBundle830G3)
}

func TestValidateBatchPublishedBaseHistory830G3UsesExactParentBindingsAndSourceUnion(t *testing.T) {
	parent := fixtureBundleForIncrementalTest830G3(t)
	var err error
	child := parent
	child.Request.BaseRequest.BaseReleaseID = "release-platform-parent"
	child.Request.BaseRequest.BaseActivationEpoch = 6
	binding := PublishedBaseBinding830G3{
		Contract:        "published-base-binding.830.g3.v1",
		ReleaseID:       child.Request.BaseRequest.BaseReleaseID,
		ActivationEpoch: child.Request.BaseRequest.BaseActivationEpoch,
		CandidateSHA256: parent.CandidateHash,
		ManifestDigest:  strings.Repeat("a", 64),
		EntityBindings:  parent.Request.EntityBindings,
	}
	binding.BindingSHA256, err = batchConceptHashWithout830G3(
		binding.Contract, binding, "binding_sha256",
	)
	require.NoError(t, err)
	child.Request.PublishedBase = &binding
	require.NoError(t, ValidateBatchPublishedBaseHistory830G3(
		parent, child, binding.ReleaseID, binding.ActivationEpoch, binding.ManifestDigest,
	))

	changed := child
	changed.Request.BaseRequest.Sources = append(
		append([]ConceptSourceBlock830G2(nil), child.Request.BaseRequest.Sources...),
		child.Request.BaseRequest.Sources[0],
	)
	changed.Request.BaseRequest.Sources[len(changed.Request.BaseRequest.Sources)-1].BlockID = "unexpected-block"
	require.ErrorIs(t, ValidateBatchPublishedBaseHistory830G3(
		parent, changed, binding.ReleaseID, binding.ActivationEpoch, binding.ManifestDigest,
	), ErrConceptCandidateBundle830G3)

	changed = child
	forged := binding
	forged.EntityBindings = append([]EntityCompileBinding830G3(nil), binding.EntityBindings...)
	forged.EntityBindings[0].DisplayName += " changed"
	forged.BindingSHA256, err = batchConceptHashWithout830G3(
		forged.Contract, forged, "binding_sha256",
	)
	require.NoError(t, err)
	changed.Request.PublishedBase = &forged
	require.ErrorIs(t, ValidateBatchPublishedBaseHistory830G3(
		parent, changed, binding.ReleaseID, binding.ActivationEpoch, binding.ManifestDigest,
	), ErrConceptCandidateBundle830G3)
}

func TestFieldRefresh830G3RequiresSortedUniqueRows(t *testing.T) {
	rows := []FieldRefresh830G3{
		{EntityID: "entity-a", FieldKey: "field-a"},
		{EntityID: "entity-a", FieldKey: "field-b"},
	}
	require.NoError(t, validateFieldRefreshRows830G3(rows))
	require.ErrorIs(t, validateFieldRefreshRows830G3([]FieldRefresh830G3{rows[1], rows[0]}), ErrConceptCandidateBundle830G3)
	require.ErrorIs(t, validateFieldRefreshRows830G3([]FieldRefresh830G3{rows[0], rows[0]}), ErrConceptCandidateBundle830G3)
}

func TestAlignedFields830G3ExcludesOnlyExplicitRefresh(t *testing.T) {
	bundle := fixtureBundleForIncrementalTest830G3(t)
	require.NotEmpty(t, bundle.Request.BaseRequest.ExistingFields)
	selected := bundle.Request.BaseRequest.ExistingFields[0]
	bundle.Request.RefreshFields = []FieldRefresh830G3{{
		EntityID: selected.EntityID, FieldKey: selected.FieldKey,
	}}
	aligned, err := alignedFields830G3(bundle.Request)
	require.NoError(t, err)
	require.Len(t, aligned, len(bundle.Request.BaseRequest.ExistingFields)-1)
	for _, field := range aligned {
		require.NotEqual(t, selected.EntityID+"\x00"+selected.FieldKey, field.EntityID+"\x00"+field.FieldKey)
	}
}

func TestCurrentBindingIDs830G3RejectsPartialOrSameMaterialReferenceDrift(t *testing.T) {
	bundle := fixtureBundleForIncrementalTest830G3(t)
	var err error
	typed, err := decodeResolutionInputs830G3(bundle.Request.ResolutionInputs, bundle.Request.Resolution)
	require.NoError(t, err)
	current, err := currentBindingIDs830G3(bundle.Request.EntityBindings, typed)
	require.NoError(t, err)
	require.Len(t, current, len(bundle.Request.EntityBindings))
	require.NoError(t, validateBindingsAgainstResolution830G3(bundle.Request, typed, current))
	entries, _, err := corpusIndexes830G3(bundle.Request.ResolutionInputs.Corpus)
	require.NoError(t, err)
	require.NoError(t, validateRequestSourceClosure830G3(bundle.Request, entries, current))
	binding := bundle.Request.EntityBindings[0]

	partial := binding
	partial.ResolutionRefs = append(
		append([]ResolutionDecisionRef830G3(nil), binding.ResolutionRefs...),
		ResolutionDecisionRef830G3{
			MaterialID:                     "material-not-current",
			ProposalRef:                    "proposal-not-current",
			DecisionSHA256:                 strings.Repeat("a", 64),
			ClassificationAssignmentSHA256: strings.Repeat("b", 64),
		},
	)
	_, err = currentBindingIDs830G3([]EntityCompileBinding830G3{partial}, typed)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)

	sameMaterialDrift := binding
	sameMaterialDrift.ResolutionRefs = append([]ResolutionDecisionRef830G3(nil), binding.ResolutionRefs...)
	sameMaterialDrift.ResolutionRefs[0].ProposalRef = "proposal-not-current"
	_, err = currentBindingIDs830G3([]EntityCompileBinding830G3{sameMaterialDrift}, typed)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
}
