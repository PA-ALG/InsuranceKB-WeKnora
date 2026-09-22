package types

import (
	"encoding/json"
	"os"
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestEvidenceIdentityV3PreservesCompleteV1V2Decisions830G3(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(raw, &bundle))
	for _, version := range []string{"batch-entity-resolution-compiler.830.g3.v1", "batch-entity-resolution-compiler.830.g3.v2", "batch-entity-resolution-compiler.830.g3.v3"} {
		t.Run(version, func(t *testing.T) {
			typed, err := decodeResolutionInputs830G3(bundle.Request.ResolutionInputs, bundle.Request.Resolution)
			require.NoError(t, err)
			typed.Resolution.CompilerVersion = version
			typed.Resolution.BatchSHA256, err = batchConceptHashWithout830G3(typed.Resolution.Contract, typed.Resolution, "batch_sha256")
			require.NoError(t, err)
			require.NoError(t, validateResolutionReplay830G3(bundle.Request.Catalog, bundle.Request.ResolutionInputs, typed))
		})
	}
}

type identityVectorV3_830G3 struct {
	CatalogFixture string                      `json:"catalog_fixture"`
	CatalogSHA256  string                      `json:"catalog_sha256"`
	Catalog        SchemaPackCatalog830G3      `json:"catalog"`
	Inputs         BatchResolutionInputs830G3  `json:"inputs"`
	Resolutions    []json.RawMessage           `json:"resolutions"`
	Bindings       []EntityCompileBinding830G3 `json:"bindings"`
}

func readIdentityVectorV3_830G3(t *testing.T) identityVectorV3_830G3 {
	t.Helper()
	raw, err := os.ReadFile("testdata/concept_identity_joint_830_g3_vector.json")
	require.NoError(t, err)
	var wire identityVectorV3_830G3
	require.NoError(t, json.Unmarshal(raw, &wire))
	require.Len(t, wire.Resolutions, 3)
	require.Equal(t, batchConceptFixture830G3, wire.CatalogFixture)
	existing, err := os.ReadFile(wire.CatalogFixture)
	require.NoError(t, err)
	var old BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(existing, &old))
	wire.Catalog = old.Request.Catalog
	require.Equal(t, wire.CatalogSHA256, wire.Catalog.CatalogSHA256)
	return wire
}

func TestEvidenceIdentityV3PythonFrozenVector830G3(t *testing.T) {
	wire := readIdentityVectorV3_830G3(t)
	for _, raw := range wire.Resolutions {
		typed, err := decodeResolutionInputs830G3(wire.Inputs, raw)
		require.NoError(t, err)
		t.Run(typed.Resolution.CompilerVersion, func(t *testing.T) {
			before, err := json.Marshal(typed.Proposals)
			require.NoError(t, err)
			require.NoError(t, validateResolutionReplay830G3(wire.Catalog, wire.Inputs, typed))
			after, err := json.Marshal(typed.Proposals)
			require.NoError(t, err)
			require.Equal(t, string(before), string(after), "joint decisions must not rewrite source proposals")
			if typed.Resolution.CompilerVersion == evidenceIdentityCompilerV3_830G3 {
				require.Equal(t, 3, typed.Resolution.DispositionCounts.Create)
				request := BatchConceptCompileRequest830G3{EntityBindings: wire.Bindings}
				require.NoError(t, validateBindingsAgainstResolution830G3(request, typed))
				for _, decision := range typed.Resolution.Decisions {
					require.Equal(t, "CREATE", decision.Disposition)
					require.Equal(t, typed.Resolution.Decisions[0].Children[0].Anchors, decision.Children[0].Anchors)
				}
			}
		})
	}
}

func TestEvidenceIdentityV3BindingRequiresSupportingMaterial830G3(t *testing.T) {
	wire := readIdentityVectorV3_830G3(t)
	typed, err := decodeResolutionInputs830G3(wire.Inputs, wire.Resolutions[2])
	require.NoError(t, err)
	require.Equal(t, evidenceIdentityCompilerV3_830G3, typed.Resolution.CompilerVersion)
	require.Len(t, wire.Bindings, 1)
	binding := wire.Bindings[0]
	require.Len(t, binding.ResolutionRefs, 3)
	dropped := binding.ResolutionRefs[0].MaterialID
	binding.ResolutionRefs = append([]ResolutionDecisionRef830G3{}, binding.ResolutionRefs[1:]...)
	binding.SourceMaterialIDs = append([]string{}, binding.SourceMaterialIDs[1:]...)
	evidence := []BoundResolutionEvidence830G3{}
	for _, e := range binding.ResolutionEvidence {
		if e.MaterialID != dropped {
			evidence = append(evidence, e)
		}
	}
	binding.ResolutionEvidence = evidence
	binding.BindingSHA256, err = batchConceptHashWithout830G3(binding.Contract, binding, "binding_sha256")
	require.NoError(t, err)
	require.ErrorIs(t, validateBindingsAgainstResolution830G3(BatchConceptCompileRequest830G3{EntityBindings: []EntityCompileBinding830G3{binding}}, typed), ErrConceptCandidateBundle830G3)
}

func TestEvidenceIdentityV3RechecksSupportAndConflicts830G3(t *testing.T) {
	for _, mode := range []string{"missing_issuer_support", "source_drift", "issuer_conflict", "schema_conflict", "version_conflict", "untrusted_role"} {
		t.Run(mode, func(t *testing.T) {
			wire := readIdentityVectorV3_830G3(t)
			typed, err := decodeResolutionInputs830G3(wire.Inputs, wire.Resolutions[2])
			require.NoError(t, err)
			proposals := typed.Proposals
			switch mode {
			case "missing_issuer_support":
				proposals.Proposals[0].Entities[0].Issuer = nil
			case "source_drift":
				wire.Inputs.Corpus.Entries[0].Blocks[0].Text = "changed " + wire.Inputs.Corpus.Entries[0].Blocks[0].Text
			case "issuer_conflict":
				issuer := "平安测试医疗保险"
				proposals.Proposals[1].Entities[0].Issuer = &issuer
				addOwnConflictEvidenceV3_830G3(t, &proposals.Proposals[1], wire.Inputs.Corpus.Entries[1].Blocks[0], "issuer", issuer)
			case "schema_conflict":
				proposals.Proposals[1].Entities[0].PrimaryLabel = "whole_life_insurance"
				proposals.Proposals[1].Entities[0].Labels[0].TaxonomyLabel = "whole_life_insurance"
			case "version_conflict":
				version := "REG1"
				proposals.Proposals[0].Entities[0].VersionLabel = &version
				addOwnConflictEvidenceV3_830G3(t, &proposals.Proposals[0], wire.Inputs.Corpus.Entries[0].Blocks[0], "version", version)
			case "untrusted_role":
				proposals.Proposals[0].MaterialRole = "untrusted"
			}
			before, err := json.Marshal(proposals)
			require.NoError(t, err)
			expected, err := expectedResolutionDecisions830G3(wire.Catalog, wire.Inputs.Corpus, proposals, typed.Existing, typed.Policy, true, true)
			require.NoError(t, err)
			require.False(t, reflect.DeepEqual(expected, typed.Resolution.Decisions), "changed support cannot reuse the old joint decisions")
			if mode == "issuer_conflict" || mode == "version_conflict" || mode == "schema_conflict" {
				for _, parent := range expected {
					require.Equal(t, "NEEDS_CONFIRM", parent.Disposition)
					require.Contains(t, parent.Children[0].ReasonCodes, "AMBIGUOUS_IDENTITY")
				}
			}
			after, err := json.Marshal(proposals)
			require.NoError(t, err)
			require.Equal(t, string(before), string(after))
		})
	}
}

func addOwnConflictEvidenceV3_830G3(t *testing.T, proposal *MaterialProposal830G3, block ConceptSourceBlock830G2, purpose, value string) {
	t.Helper()
	at := strings.Index(block.Text, value)
	require.GreaterOrEqual(t, at, 0)
	ref := proposal.Entities[0].ProposalRef
	id := proposal.MaterialID + "-joint-conflict"
	proposal.Evidence = append(append([]ProposalEvidence830G3{}, proposal.Evidence...), ProposalEvidence830G3{EvidenceID: id, EntityProposalRef: &ref, Purpose: purpose, Evidence: sourceSpanV2_830G3(block, at, at+len(value))})
	proposal.Entities[0].IdentityEvidenceIDs = append(append([]string{}, proposal.Entities[0].IdentityEvidenceIDs...), id)
	sort.Strings(proposal.Entities[0].IdentityEvidenceIDs)
	sort.Slice(proposal.Evidence, func(i, j int) bool { return proposal.Evidence[i].EvidenceID < proposal.Evidence[j].EvidenceID })
}

func TestEvidenceIdentityV3JointExistingTarget830G3(t *testing.T) {
	for _, mode := range []string{"one_match", "multiple_targets", "other_code_same_name", "other_issuer"} {
		t.Run(mode, func(t *testing.T) {
			wire := readIdentityVectorV3_830G3(t)
			typed, err := decodeResolutionInputs830G3(wire.Inputs, wire.Resolutions[2])
			require.NoError(t, err)
			anchor := typed.Resolution.Decisions[0].Children[0].Anchors
			item := ExistingEntity830G3{EntityID: "published-product", EntityVersion: "published-product@1", Issuer: anchor.Issuer.ObservedValue, Name: anchor.Name.ObservedValue, ProductCode: anchor.ProductCode.ObservedValue, VersionLabel: anchor.VersionLabel.ObservedValue, FilingOrRegistration: VersionAnchor830G3{Kind: anchor.VersionAnchor.Kind, Value: anchor.VersionAnchor.ObservedValue}, ApprovedAliases: []ApprovedAlias830G3{}, IdentityEvidenceSHA256s: []string{}}
			typed.Existing.Entities = []ExistingEntity830G3{item}
			expectedDisposition := "MATCH"
			switch mode {
			case "multiple_targets":
				copy := item
				copy.EntityID = "other-product"
				copy.EntityVersion = "other-product@1"
				typed.Existing.Entities = append(typed.Existing.Entities, copy)
				expectedDisposition = "NEEDS_CONFIRM"
			case "other_code_same_name":
				copy := item
				copy.ProductCode = "OTHER"
				copy.EntityID = "other-product"
				typed.Existing.Entities = append(typed.Existing.Entities, copy)
				expectedDisposition = "NEEDS_CONFIRM"
			case "other_issuer":
				typed.Existing.Entities[0].Issuer = "different insurer"
				expectedDisposition = "QUARANTINE"
			}
			expected, err := expectedResolutionDecisions830G3(wire.Catalog, wire.Inputs.Corpus, typed.Proposals, typed.Existing, typed.Policy, true, true)
			require.NoError(t, err)
			for _, parent := range expected {
				require.Equal(t, expectedDisposition, parent.Disposition)
			}
			if mode == "one_match" {
				typed.Resolution.Decisions = expected
				binding := wire.Bindings[0]
				binding.ResolutionDisposition = "MATCH"
				binding.EntityID, binding.EntityVersion = item.EntityID, item.EntityVersion
				binding.CandidateID, binding.EntityCandidateSHA256 = nil, nil
				for i := range binding.ResolutionRefs {
					binding.ResolutionRefs[i].DecisionSHA256 = expected[i].Children[0].DecisionSHA256
				}
				require.NoError(t, validateBindingsAgainstResolution830G3(BatchConceptCompileRequest830G3{EntityBindings: []EntityCompileBinding830G3{binding}}, typed))
				binding.ResolutionRefs = binding.ResolutionRefs[1:]
				require.ErrorIs(t, validateBindingsAgainstResolution830G3(BatchConceptCompileRequest830G3{EntityBindings: []EntityCompileBinding830G3{binding}}, typed), ErrConceptCandidateBundle830G3)
			}
		})
	}
}
