package types

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func sha256Hex830G3(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func fixtureMap830G3(t *testing.T) map[string]any {
	t.Helper()
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var value map[string]any
	require.NoError(t, decoder.Decode(&value))
	return value
}

func map830G3(t *testing.T, value any) map[string]any {
	t.Helper()
	result, ok := value.(map[string]any)
	require.True(t, ok)
	return result
}

func slice830G3(t *testing.T, value any) []any {
	t.Helper()
	result, ok := value.([]any)
	require.True(t, ok)
	return result
}

func rehashMap830G3(t *testing.T, value map[string]any, domain, field string) {
	t.Helper()
	delete(value, field)
	digest, err := batchConceptHash830G3(domain, value)
	require.NoError(t, err)
	value[field] = digest
}

func rehashCandidateMap830G3(t *testing.T, candidate map[string]any) []byte {
	t.Helper()
	request := map830G3(t, candidate["request"])
	inputs := map830G3(t, request["resolution_inputs"])
	proposals := map830G3(t, inputs["proposals"])
	for _, rawProposal := range slice830G3(t, proposals["proposals"]) {
		rehashMap830G3(t, map830G3(t, rawProposal), "material-proposal.830.g3.v1", "proposal_sha256")
	}
	rehashMap830G3(t, proposals, "batch-identity-proposals.830.g3.v1", "proposals_sha256")
	rehashMap830G3(t, inputs, "batch-resolution-inputs.830.g3.v1", "inputs_sha256")
	resolution := map830G3(t, request["resolution"])
	resolution["proposals_sha256"] = proposals["proposals_sha256"]
	rehashMap830G3(t, resolution, "batch-entity-resolution.830.g3.v1", "batch_sha256")
	rehashMap830G3(t, request, "batch-concept-compile-request.830.g3.v1", "request_sha256")

	baseRequest := map830G3(t, request["base_request"])
	var typedBaseRequest ConceptCompileRequest830G2
	baseRequestRaw, err := json.Marshal(baseRequest)
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(baseRequestRaw, &typedBaseRequest))
	baseRequestHash, err := compileRequestHash830G3(typedBaseRequest)
	require.NoError(t, err)
	modelResult := map830G3(t, candidate["model_compile_result"])
	modelExecution := map830G3(t, modelResult["execution"])
	compilerContext := map[string]any{
		"request": request, "request_sha256": request["request_sha256"],
		"base_request_hash": baseRequestHash, "output_mode": "NEW_MEMBERS_ONLY",
	}
	compilerContextHash, err := batchConceptHash830G3("batch-concept-compile-context.830.g3.v1", compilerContext)
	require.NoError(t, err)
	modelExecution["context_hash"] = compilerContextHash
	modelExecutionHash, err := batchConceptHash830G3("batch-concept-model-execution.830.g3.v1", modelExecution)
	require.NoError(t, err)
	var modelOutput ConceptCompileOutput830G2
	modelOutputRaw, err := json.Marshal(modelResult["output"])
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(modelOutputRaw, &modelOutput))
	modelOutputHash, err := compileOutputHash830G3(modelOutput)
	require.NoError(t, err)
	carryContextHash, err := batchConceptHash830G3("batch-concept-carry-context.830.g3.v1", map[string]any{
		"request_sha256":                 request["request_sha256"],
		"model_compile_output_hash":      modelOutputHash,
		"model_compile_execution_sha256": modelExecutionHash,
	})
	require.NoError(t, err)
	map830G3(t, map830G3(t, candidate["compile_result"])["execution"])["context_hash"] = carryContextHash
	var finalOutput ConceptCompileOutput830G2
	finalOutputRaw, err := json.Marshal(map830G3(t, candidate["compile_result"])["output"])
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(finalOutputRaw, &finalOutput))
	finalHash, err := compileOutputHash830G3(finalOutput)
	require.NoError(t, err)
	reviewContextHash, err := batchConceptHash830G3("batch-concept-review-context.830.g3.v1", map[string]any{
		"request": request, "candidate": map830G3(t, candidate["compile_result"])["output"],
		"request_sha256": request["request_sha256"], "base_request_hash": baseRequestHash,
		"output_hash": finalHash,
	})
	require.NoError(t, err)
	map830G3(t, map830G3(t, candidate["review_result"])["execution"])["context_hash"] = reviewContextHash
	rehashMap830G3(t, candidate, conceptBatchContract830G3, "candidate_hash")
	raw, err := json.Marshal(candidate)
	require.NoError(t, err)
	return raw
}

func rehashCorpusCandidateMap830G3(t *testing.T, candidate map[string]any) []byte {
	t.Helper()
	request := map830G3(t, candidate["request"])
	inputs := map830G3(t, request["resolution_inputs"])
	corpus := map830G3(t, inputs["corpus"])
	entries := slice830G3(t, corpus["entries"])
	entryHashes := make(map[string]any, len(entries))
	for _, rawEntry := range entries {
		entry := map830G3(t, rawEntry)
		rehashMap830G3(t, entry, "corpus-entry.830.g3.v1", "entry_sha256")
		entryHashes[entry["material_id"].(string)] = entry["entry_sha256"]
	}
	rehashMap830G3(t, corpus, "batch-corpus.830.g3.v1", "corpus_sha256")
	proposals := map830G3(t, inputs["proposals"])
	proposals["corpus_sha256"] = corpus["corpus_sha256"]
	for _, rawProposal := range slice830G3(t, proposals["proposals"]) {
		proposal := map830G3(t, rawProposal)
		proposal["corpus_entry_sha256"] = entryHashes[proposal["material_id"].(string)]
	}
	for _, rawReceipt := range slice830G3(t, proposals["model_receipts"]) {
		receipt := map830G3(t, rawReceipt)
		bindings := slice830G3(t, receipt["material_bindings"])
		for _, rawBinding := range bindings {
			binding := map830G3(t, rawBinding)
			binding["corpus_entry_sha256"] = entryHashes[binding["material_id"].(string)]
		}
		inputHash, err := batchConceptHash830G3("batch-classifier-input.830.g3.v1", map[string]any{
			"corpus_sha256": corpus["corpus_sha256"], "material_bindings": bindings,
		})
		require.NoError(t, err)
		receipt["input_sha256"] = inputHash
	}
	resolution := map830G3(t, request["resolution"])
	resolution["corpus_sha256"] = corpus["corpus_sha256"]
	return rehashCandidateMap830G3(t, candidate)
}

const batchConceptFixture830G3 = "../../harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json"
const batchConceptPreparation830G3 = "../../harness/tests/fixtures/batch_concept_compile_830_g3/preparation-request.json"

func TestParseBatchConceptCandidateBundle830G3ValidatesActual342Fixture(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var decoded BatchConceptCandidateBundle830G3
	require.NoError(t, decodeExactObject830G3(raw, &decoded, batchBundleKeys830G3, true))
	require.NoError(t, validateBatchRequest830G3(decoded.Request))
	require.NoError(t, validateDelta830G3(decoded.Request, decoded.ModelCompileResult.Output))

	bundle, canonical, err := CanonicalBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	require.Equal(t, raw, canonical)
	require.Equal(t, "e9f3fc9bec2cca609a30dce0f015a6af955e41da9d7a42399b05164efef14870", bundle.CandidateHash)
	require.Equal(t, "40920c09c42a9b28f1b8348c34d0bd9b63dde7568fc90c11311d554b7b6e25ec", bundle.Request.RequestSHA256)
	require.Len(t, bundle.Request.BaseRequest.ExistingFields, 134)
	require.Len(t, bundle.Request.UnknownFieldKeyAlignments, 2)
	require.Len(t, bundle.ModelCompileResult.Output.Fields, 208)
	require.Len(t, bundle.CompileResult.Output.Fields, 342)
	require.Len(t, bundle.PageManifest.Members, 354)
	require.Len(t, bundle.Request.BaseRequest.Sources, 27)
	for _, entry := range bundle.Request.ResolutionInputs.Corpus.Entries {
		require.Equal(t, "knowledge-revision-source.v1", entry.Receipt.Contract)
		require.NotNil(t, entry.Receipt.Registered)
		require.Nil(t, entry.Receipt.Legacy)
	}

	snapshots, err := bundle.SnapshotMembers()
	require.NoError(t, err)
	require.Len(t, snapshots, 354)
	for index, snapshot := range snapshots {
		require.Equal(t, bundle.PageManifest.Members[index].MemberID, snapshot.LogicalSlug)
		require.Equal(t, bundle.CandidateHash, snapshot.RevisionID)
		require.Regexp(t, "^[0-9a-f]{64}$", snapshot.MemberDigest)
	}
}

func TestBatchConceptRequest830G3ValidatesFrozenComponents(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var decoded BatchConceptCandidateBundle830G3
	require.NoError(t, decodeExactObject830G3(raw, &decoded, batchBundleKeys830G3, true))
	request := decoded.Request
	require.NoError(t, validateConceptRequest830G2(request.BaseRequest))
	catalogRaw, err := conceptCanonicalJSON830G2(request.Catalog)
	require.NoError(t, err)
	require.Equal(t, request.CatalogWireSHA256, sha256Hex830G3(catalogRaw))
	expectedCatalog, err := batchConceptHashWithout830G3(request.Catalog.Contract, request.Catalog, "catalog_sha256")
	require.NoError(t, err)
	require.Equal(t, request.Catalog.CatalogSHA256, expectedCatalog)
	for index, entry := range request.Catalog.Entries {
		expectedPack, hashErr := batchConceptHashWithout830G3(entry.Pack.Contract, entry.Pack, "schema_pack_sha256")
		require.NoError(t, hashErr, index)
		require.Equal(t, entry.Pack.SchemaPackSHA256, expectedPack, index)
		require.NoError(t, validateEntityPageProfile830G1(entry.Profile), index)
		for fieldIndex, field := range entry.Pack.Fields {
			metadata := map[string]any{
				"field_key": field.FieldKey, "short_title": field.ShortTitle,
				"schema_category": field.SchemaCategory, "value_spec": field.ValueSpec,
				"description": field.Description, "source_guidance": field.SourceGuidance,
				"formation_method": field.FormationMethod, "knowledge_role": field.KnowledgeRole,
				"common_field_marker":       field.CommonFieldMarker,
				"other_applicable_products": field.OtherApplicableProduct,
				"usage_frequency":           field.UsageFrequency,
			}
			expectedField, hashErr := batchConceptHash830G3(
				"schema-field-definition.830.g3.v1",
				map[string]any{"schema_pack_id": entry.Pack.SchemaPackID, "field": metadata},
			)
			require.NoError(t, hashErr, index, fieldIndex)
			require.Equal(t, field.SemanticSHA256, expectedField, index, fieldIndex)
		}
	}
	require.NoError(t, validateSchemaCatalog830G3(request.Catalog, request.CatalogWireSHA256))
	require.NoError(t, validateProfileConfirmation830G3(request.ProfileConfirmation, request.Catalog))
	require.NoError(t, validateBatchCorpus830G3(request.ResolutionInputs.Corpus))
	require.True(t, hashEqualWithout830G3(request.ResolutionInputs.Contract, request.ResolutionInputs, "inputs_sha256", request.ResolutionInputs.InputsSHA256))
	var proposalPayload map[string]any
	decoder := json.NewDecoder(bytes.NewReader(request.ResolutionInputs.Proposals))
	decoder.UseNumber()
	require.NoError(t, decoder.Decode(&proposalPayload))
	proposalActual := proposalPayload["proposals_sha256"].(string)
	delete(proposalPayload, "proposals_sha256")
	proposalExpected, err := batchConceptHash830G3("batch-identity-proposals.830.g3.v1", proposalPayload)
	require.NoError(t, err)
	require.Equal(t, proposalActual, proposalExpected)
	var decodedProposal map[string]any
	require.NoError(t, decodeExactObject830G3(request.ResolutionInputs.Proposals, &decodedProposal, proposalKeys830G3, true))
	_, err = validateRawContractHash830G3(request.ResolutionInputs.Proposals, "batch-identity-proposals.830.g3.v1", "proposals_sha256", proposalKeys830G3)
	require.NoError(t, err)
	_, err = validateRawContractHash830G3(request.ResolutionInputs.ExistingEntities, "existing-entities.830.g3.v1", "snapshot_sha256", existingKeys830G3)
	require.NoError(t, err)
	_, err = validateRawContractHash830G3(request.ResolutionInputs.Policy, "batch-resolution-policy.830.g3.v1", "policy_sha256", policyKeys830G3)
	require.NoError(t, err)
	_, _, _, err = validateResolutionInputs830G3(request.ResolutionInputs)
	require.NoError(t, err)
	var resolution batchResolutionSummary830G3
	require.NoError(t, decodeExactObject830G3(request.Resolution, &resolution, resolutionKeys830G3, true))
	require.True(t, hashEqualWithout830G3(resolution.Contract, resolution, "batch_sha256", resolution.BatchSHA256))
	var payload map[string]any
	require.NoError(t, json.Unmarshal(request.Resolution, &payload))
	require.NotEmpty(t, payload)
}

func TestBatchConceptPublishedG3BaseIdentityIsExact(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, decodeExactObject830G3(raw, &bundle, batchBundleKeys830G3, true))
	base := bundle.Request.BaseRequest
	base.BaseReleaseID = "release-next-g3-test"
	base.BaseActivationEpoch = 6
	base.ExistingDefinitions = bundle.CompileResult.Output.Definitions
	base.ExistingFields = bundle.CompileResult.Output.Fields
	base.ExistingPages = bundle.CompileResult.Output.Pages
	base.ExistingEntityVersions = base.EntityVersions

	kind, err := batchConceptBaseKind830G3(base)
	require.NoError(t, err)
	require.Equal(t, batchConceptBasePublishedG3, kind)

	base.ExistingFields = base.ExistingFields[:len(base.ExistingFields)-1]
	_, err = batchConceptBaseKind830G3(base)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
}

func navigationFixture830G3(t *testing.T) (BatchConceptCandidateBundle830G3, BatchConceptCandidateBundle830G3, NavigationAssignment830G3) {
	t.Helper()
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	parent, err := ParseBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	child := parent
	child.Request.BaseRequest.BaseReleaseID = "release-navigation-test"
	child.Request.BaseRequest.BaseActivationEpoch = 6
	child.Request.BaseRequest.ExistingFields = parent.CompileResult.Output.Fields
	child.Request.BaseRequest.ExistingDefinitions = parent.CompileResult.Output.Definitions
	child.Request.BaseRequest.ExistingPages = parent.CompileResult.Output.Pages
	child.Request.BaseRequest.ExistingEntityVersions = parent.Request.BaseRequest.EntityVersions
	child.ModelCompileResult.Execution.Implementation = "published-content-identity-reuse.830.g3.v1"
	child.ModelCompileResult.Output.Definitions = []ConceptDefinition830G2{}
	child.ModelCompileResult.Output.Fields = []ConceptFieldAssertion830G2{}
	child.ModelCompileResult.Output.Pages = []ConceptFreeWikiPage830G2{}
	child.ModelCompileResult.Output.Audit = []ConceptAuditDisposition830G2{}
	binding := parent.Request.EntityBindings[0]
	previous, err := DefaultNavigationAssignmentHash830G3(binding)
	require.NoError(t, err)
	row := NavigationAssignment830G3{Contract: "g3-navigation-assignment.830.v1", EntityID: binding.EntityID,
		EntityVersion: binding.EntityVersion, AssignmentVersion: 1, Labels: []string{binding.PrimaryClassification, "健康保障"},
		PrimaryLabel: "健康保障", PreviousAssignmentSHA256: previous}
	row.AssignmentSHA256, err = batchConceptHashWithout830G3(row.Contract, row, "assignment_sha256")
	require.NoError(t, err)
	child.NavigationAssignments = []NavigationAssignment830G3{row}
	return parent, child, row
}

func TestBatchNavigationAssignment830G3PreservesBusinessAndProjectsOverview(t *testing.T) {
	parent, child, row := navigationFixture830G3(t)
	require.NoError(t, validateNavigationAssignments830G3(child))
	require.NoError(t, ValidateBatchNavigationHistory830G3(parent, child))
	before, err := projectBatchMembers830G3(parent.Request, parent.CompileResult.Output)
	require.NoError(t, err)
	after, err := projectBatchMembers830G3(parent.Request, parent.CompileResult.Output, child.NavigationAssignments)
	require.NoError(t, err)
	for index, member := range before.Members {
		if member.Kind != "entity_overview" || member.OwnerID != row.EntityID {
			require.Equal(t, member, after.Members[index], "factual members and evidence remain exact")
			continue
		}
		var overview EntityDirectoryEntry830G3
		require.NoError(t, json.Unmarshal(after.Members[index].Payload, &overview))
		require.Equal(t, &row, overview.NavigationAssignment)
		require.Equal(t, parent.Request.EntityBindings[0].SchemaPackSHA256, overview.SchemaPackSHA256)
	}
}

func TestBatchNavigationAssignment830G3RejectsDropStaleAndPackDrift(t *testing.T) {
	parent, child, row := navigationFixture830G3(t)
	row.PreviousAssignmentSHA256 = strings.Repeat("a", 64)
	row.AssignmentSHA256, _ = batchConceptHashWithout830G3(row.Contract, row, "assignment_sha256")
	child.NavigationAssignments = []NavigationAssignment830G3{row}
	require.Error(t, ValidateBatchNavigationHistory830G3(parent, child))
	parent, child, row = navigationFixture830G3(t)
	parent.NavigationAssignments = []NavigationAssignment830G3{row}
	child.NavigationAssignments = nil
	require.Error(t, ValidateBatchNavigationHistory830G3(parent, child), "an existing assignment cannot disappear")
	child.NavigationAssignments = []NavigationAssignment830G3{row}
	require.NoError(t, ValidateBatchNavigationHistory830G3(parent, child), "unchanged assignments carry exactly")
	child.Request.EntityBindings = append([]EntityCompileBinding830G3(nil), child.Request.EntityBindings...)
	child.Request.EntityBindings[0].SchemaPackSHA256 = strings.Repeat("b", 64)
	row.AssignmentVersion++
	row.PreviousAssignmentSHA256 = row.AssignmentSHA256
	row.AssignmentSHA256, _ = batchConceptHashWithout830G3(row.Contract, row, "assignment_sha256")
	child.NavigationAssignments = []NavigationAssignment830G3{row}
	require.Error(t, ValidateBatchNavigationHistory830G3(parent, child))
}

func TestBatchNavigationAssignment830G3RestorationAppendsHistory(t *testing.T) {
	parent, child, row := navigationFixture830G3(t)
	parent.NavigationAssignments = []NavigationAssignment830G3{row}
	row.AssignmentVersion++
	row.PreviousAssignmentSHA256 = row.AssignmentSHA256
	row.PrimaryLabel = parent.Request.EntityBindings[0].PrimaryClassification
	row.Labels = []string{row.PrimaryLabel}
	row.AssignmentSHA256, _ = batchConceptHashWithout830G3(row.Contract, row, "assignment_sha256")
	child.NavigationAssignments = []NavigationAssignment830G3{row}
	require.NoError(t, validateNavigationAssignments830G3(child))
	require.NoError(t, ValidateBatchNavigationHistory830G3(parent, child))
	row.AssignmentVersion = 4
	child.NavigationAssignments[0] = row
	require.Error(t, ValidateBatchNavigationHistory830G3(parent, child))
}

func TestBatchNavigationAssignment830G3RejectsInvalidDisplayMetadata(t *testing.T) {
	_, basis, _ := navigationFixture830G3(t)
	for name, mutate := range map[string]func(*BatchConceptCandidateBundle830G3){
		"legacy base": func(b *BatchConceptCandidateBundle830G3) { b.Request.BaseRequest.BaseActivationEpoch = 5 },
		"unsorted labels": func(b *BatchConceptCandidateBundle830G3) {
			b.NavigationAssignments[0].Labels = []string{"健康保障", "critical_illness"}
		},
		"duplicate labels": func(b *BatchConceptCandidateBundle830G3) {
			b.NavigationAssignments[0].Labels = []string{"健康保障", "健康保障"}
		},
		"too long": func(b *BatchConceptCandidateBundle830G3) {
			b.NavigationAssignments[0].Labels = []string{strings.Repeat("保", 81)}
		},
		"whitespace": func(b *BatchConceptCandidateBundle830G3) {
			b.NavigationAssignments[0].Labels = []string{" 健康保障"}
		},
		"unknown entity": func(b *BatchConceptCandidateBundle830G3) { b.NavigationAssignments[0].EntityID = "unbound" },
		"zero version":   func(b *BatchConceptCandidateBundle830G3) { b.NavigationAssignments[0].AssignmentVersion = 0 },
		"duplicate rows": func(b *BatchConceptCandidateBundle830G3) {
			b.NavigationAssignments = append(b.NavigationAssignments, b.NavigationAssignments[0])
		},
	} {
		t.Run(name, func(t *testing.T) {
			child := basis
			child.NavigationAssignments = append([]NavigationAssignment830G3(nil), basis.NavigationAssignments...)
			child.NavigationAssignments[0].Labels = append([]string(nil), basis.NavigationAssignments[0].Labels...)
			mutate(&child)
			for i := range child.NavigationAssignments {
				row := &child.NavigationAssignments[i]
				row.AssignmentSHA256, _ = batchConceptHashWithout830G3(row.Contract, *row, "assignment_sha256")
			}
			require.Error(t, validateNavigationAssignments830G3(child))
		})
	}
}

func TestBatchNavigationAssignment830G3OptionalWirePreservesLegacy(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	bundle, canonical, err := CanonicalBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	require.NotContains(t, string(canonical), "navigation_assignments")
	bundle.NavigationAssignments = []NavigationAssignment830G3{}
	unchanged, err := batchConceptCanonicalJSON830G3(bundle)
	require.NoError(t, err)
	require.Equal(t, canonical, unchanged)
	for _, injected := range []string{"null", "[]"} {
		changed := append([]byte(`{"navigation_assignments":`+injected+`,`), canonical[1:]...)
		_, err := ParseBatchConceptCandidateBundle830G3(changed)
		require.Error(t, err, "explicit empty optional collections are not canonical wire")
	}
}

func TestPublishedReviewReuse830G3RequiresPublishedContentReuse(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, decodeExactObject830G3(raw, &bundle, batchBundleKeys830G3, true))
	base := &bundle.Request.BaseRequest
	base.BaseReleaseID = "release-next-g3-test"
	base.BaseActivationEpoch = 6
	base.ExistingDefinitions = bundle.CompileResult.Output.Definitions
	base.ExistingFields = bundle.CompileResult.Output.Fields
	base.ExistingPages = bundle.CompileResult.Output.Pages
	base.ExistingEntityVersions = base.EntityVersions
	bundle.ReviewResult.Execution.Implementation = "published-review-context-diff-reuse.830.g3.v1"
	bundle.ReviewResult.Output.Decision = "PASS"
	bundle.ReviewResult.Output.PageScores = map[string]ConceptValueScore830G2{}

	require.ErrorIs(t, validatePublishedReviewReuse830G3(bundle), ErrConceptCandidateBundle830G3)
	bundle.ModelCompileResult.Execution.Implementation = "published-content-identity-reuse.830.g3.v1"
	require.NoError(t, validatePublishedReviewReuse830G3(bundle))
}

func TestBatchConceptCandidateBundle830G3RejectsAmbiguousWire(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	tests := map[string][]byte{
		"duplicate top key": bytes.Replace(
			raw, []byte(`{"admission":`),
			[]byte(`{"contract":"batch-concept-candidate-bundle.830.g3.v1","admission":`), 1,
		),
		"unknown top key": bytes.Replace(
			raw, []byte(`{"admission":`), []byte(`{"unexpected":true,"admission":`), 1,
		),
		"unknown registered receipt": bytes.Replace(
			raw, []byte(`"contract":"knowledge-revision-source.v1"`),
			[]byte(`"contract":"unknown-source.v1"`), 1,
		),
		"binary float": bytes.Replace(
			raw, []byte(`"base_activation_epoch":5`), []byte(`"base_activation_epoch":5.0`), 1,
		),
	}
	for name, changed := range tests {
		t.Run(name, func(t *testing.T) {
			require.NotEqual(t, raw, changed)
			_, err := ParseBatchConceptCandidateBundle830G3(changed)
			require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
		})
	}
}

func TestBatchConceptCandidateBundle830G3RejectsNestedOmissionAndScalarNull(t *testing.T) {
	tests := map[string]func(*testing.T, map[string]any){
		"confirmation nullable actor display name omitted": func(t *testing.T, candidate map[string]any) {
			request := map830G3(t, candidate["request"])
			confirmation := map830G3(t, request["profile_confirmation"])
			delete(map830G3(t, confirmation["receipt"]), "actor_display_name")
		},
		"confirmation nullable queue owner omitted": func(t *testing.T, candidate map[string]any) {
			request := map830G3(t, candidate["request"])
			confirmation := map830G3(t, request["profile_confirmation"])
			delete(map830G3(t, confirmation["receipt"]), "queue_owner")
		},
		"match nullable candidate id omitted": func(t *testing.T, candidate map[string]any) {
			bindings := slice830G3(t, map830G3(t, candidate["request"])["entity_bindings"])
			for _, rawBinding := range bindings {
				binding := map830G3(t, rawBinding)
				if binding["resolution_disposition"] == "MATCH" {
					delete(binding, "candidate_id")
					return
				}
			}
			t.Fatal("fixture lacks MATCH binding")
		},
		"match nullable candidate hash omitted": func(t *testing.T, candidate map[string]any) {
			bindings := slice830G3(t, map830G3(t, candidate["request"])["entity_bindings"])
			for _, rawBinding := range bindings {
				binding := map830G3(t, rawBinding)
				if binding["resolution_disposition"] == "MATCH" {
					delete(binding, "entity_candidate_sha256")
					return
				}
			}
			t.Fatal("fixture lacks MATCH binding")
		},
		"embedded G2 nullable value omitted": func(t *testing.T, candidate map[string]any) {
			base := map830G3(t, map830G3(t, candidate["request"])["base_request"])
			for _, rawField := range slice830G3(t, base["existing_fields"]) {
				field := map830G3(t, rawField)
				if field["value"] == nil {
					delete(field, "value")
					return
				}
			}
			t.Fatal("fixture lacks nullable existing field value")
		},
		"embedded G2 nonnullable evidence start is null": func(t *testing.T, candidate map[string]any) {
			base := map830G3(t, map830G3(t, candidate["request"])["base_request"])
			for _, rawField := range slice830G3(t, base["existing_fields"]) {
				for _, rawEvidence := range slice830G3(t, map830G3(t, rawField)["evidence"]) {
					evidence := map830G3(t, rawEvidence)
					if evidence["start"] == json.Number("0") {
						evidence["start"] = nil
						return
					}
				}
			}
			t.Fatal("fixture lacks start=0 evidence")
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			candidate := fixtureMap830G3(t)
			mutate(t, candidate)
			raw, err := json.Marshal(candidate)
			require.NoError(t, err)
			_, err = ParseBatchConceptCandidateBundle830G3(raw)
			require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
		})
	}
}

func TestBatchConceptCandidateBundle830G3RejectsNullRequiredCollection(t *testing.T) {
	candidate := fixtureMap830G3(t)
	request := map830G3(t, candidate["request"])
	inputs := map830G3(t, request["resolution_inputs"])
	existing := map830G3(t, inputs["existing_entities"])
	entity := map830G3(t, slice830G3(t, existing["entities"])[0])
	require.Empty(t, slice830G3(t, entity["approved_aliases"]))
	entity["approved_aliases"] = nil
	rehashMap830G3(t, existing, "existing-entities.830.g3.v1", "snapshot_sha256")
	resolution := map830G3(t, request["resolution"])
	resolution["existing_snapshot_sha256"] = existing["snapshot_sha256"]

	_, err := ParseBatchConceptCandidateBundle830G3(rehashCandidateMap830G3(t, candidate))
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
}

func TestBatchConceptCandidateBundle830G3RejectsRehashedCorpusIdentityHashes(t *testing.T) {
	tests := map[string]func(*testing.T, map[string]any){
		"native capture": func(t *testing.T, entry map[string]any) {
			entry["native_capture_sha256"] = "not-a-sha256"
		},
		"parser identity": func(t *testing.T, entry map[string]any) {
			entry["parser_identity_sha256"] = "not-a-sha256"
		},
		"acquisition receipt": func(t *testing.T, entry map[string]any) {
			provenance := map830G3(t, entry["provenance"])
			provenance["acquisition_receipt_sha256"] = "not-a-sha256"
			rehashMap830G3(t, provenance, "source-provenance.830.g3.v1", "declaration_sha256")
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			candidate := fixtureMap830G3(t)
			request := map830G3(t, candidate["request"])
			inputs := map830G3(t, request["resolution_inputs"])
			corpus := map830G3(t, inputs["corpus"])
			entry := map830G3(t, slice830G3(t, corpus["entries"])[0])
			mutate(t, entry)

			_, err := ParseBatchConceptCandidateBundle830G3(rehashCorpusCandidateMap830G3(t, candidate))
			require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
		})
	}
}

func TestBatchConceptCandidateBundle830G3RejectsRehashedProposalWithoutResolutionReplay(t *testing.T) {
	candidate := fixtureMap830G3(t)
	originalRaw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	rehashedOriginal := rehashCandidateMap830G3(t, fixtureMap830G3(t))
	require.JSONEq(t, string(originalRaw), string(rehashedOriginal))
	_, err = ParseBatchConceptCandidateBundle830G3(rehashedOriginal)
	require.NoError(t, err)
	request := map830G3(t, candidate["request"])
	inputs := map830G3(t, request["resolution_inputs"])
	proposals := map830G3(t, inputs["proposals"])
	firstProposal := map830G3(t, slice830G3(t, proposals["proposals"])[0])
	firstEntity := map830G3(t, slice830G3(t, firstProposal["entities"])[0])
	firstEntity["name"] = "篡改后仍具合法格式的产品名称"

	_, err = ParseBatchConceptCandidateBundle830G3(rehashCandidateMap830G3(t, candidate))
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
}

func TestBatchConceptRequest830G3RequiresExactSelectedAndCarrySourceUnion(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, decodeExactObject830G3(raw, &bundle, batchBundleKeys830G3, true))
	entries, _, err := corpusIndexes830G3(bundle.Request.ResolutionInputs.Corpus)
	require.NoError(t, err)
	require.NoError(t, validateRequestSourceClosure830G3(bundle.Request, entries))

	missing := bundle.Request
	missing.BaseRequest.Sources = append([]ConceptSourceBlock830G2(nil), missing.BaseRequest.Sources[1:]...)
	require.ErrorIs(t, validateRequestSourceClosure830G3(missing, entries), ErrConceptCandidateBundle830G3)

	extra := bundle.Request
	extra.BaseRequest.Sources = append([]ConceptSourceBlock830G2(nil), extra.BaseRequest.Sources...)
	extraSource := extra.BaseRequest.Sources[0]
	extraSource.RevisionID = "fixture-extra-revision"
	extraSource.BlockID = "fixture-extra-block"
	extra.BaseRequest.Sources = append(extra.BaseRequest.Sources, extraSource)
	require.ErrorIs(t, validateRequestSourceClosure830G3(extra, entries), ErrConceptCandidateBundle830G3)

	tamperedEntries := make(map[string]CorpusEntry830G3, len(entries))
	for key, entry := range entries {
		tamperedEntries[key] = entry
	}
	for key, entry := range tamperedEntries {
		if len(entry.Blocks) != 0 {
			entry.Blocks = append([]ConceptSourceBlock830G2(nil), entry.Blocks...)
			entry.Blocks[0].Text += "TAMPER"
			tamperedEntries[key] = entry
			break
		}
	}
	require.ErrorIs(t, validateRequestSourceClosure830G3(bundle.Request, tamperedEntries), ErrConceptCandidateBundle830G3)
}

func TestBatchConceptDelta830G3RejectsOtherOwnerOnlyEvidence(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, decodeExactObject830G3(raw, &bundle, batchBundleKeys830G3, true))
	require.NoError(t, validateDeltaEvidence830G3(bundle.Request, bundle.ModelCompileResult.Output))
	var evidence ConceptEvidence830G2
	var sourceOwner string
	for _, field := range bundle.ModelCompileResult.Output.Fields {
		if len(field.Evidence) != 0 {
			evidence, sourceOwner = field.Evidence[0], field.EntityID
			break
		}
	}
	require.NotEmpty(t, sourceOwner)
	changed := bundle.ModelCompileResult.Output
	changed.Fields = append([]ConceptFieldAssertion830G2(nil), changed.Fields...)
	for index := range changed.Fields {
		if changed.Fields[index].EntityID != sourceOwner {
			changed.Fields[index].Evidence = []ConceptEvidence830G2{evidence}
			require.ErrorIs(t, validateDeltaEvidence830G3(bundle.Request, changed), ErrConceptCandidateBundle830G3)
			return
		}
	}
	t.Fatal("fixture lacks a second owner")
}

func TestBatchConceptBinding830G3RejectsResolutionFactDrift(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, decodeExactObject830G3(raw, &bundle, batchBundleKeys830G3, true))
	typed, err := decodeResolutionInputs830G3(bundle.Request.ResolutionInputs, bundle.Request.Resolution)
	require.NoError(t, err)
	require.NoError(t, validateBindingsAgainstResolution830G3(bundle.Request, typed))
	changed := bundle.Request
	changed.EntityBindings = append([]EntityCompileBinding830G3(nil), changed.EntityBindings...)
	changed.EntityBindings[0].DisplayName = "合法格式但不对应C决策的名称"
	require.ErrorIs(t, validateBindingsAgainstResolution830G3(changed, typed), ErrConceptCandidateBundle830G3)
}

func TestBatchConceptCandidateBundle830G3RejectsRehashedBindingAndConfirmationDrift(t *testing.T) {
	tests := map[string]func(*testing.T, map[string]any){
		"binding display name": func(t *testing.T, candidate map[string]any) {
			request := map830G3(t, candidate["request"])
			binding := map830G3(t, slice830G3(t, request["entity_bindings"])[0])
			binding["display_name"] = "不对应所选C child的名称"
			rehashMap830G3(t, binding, "entity-compile-binding.830.g3.v1", "binding_sha256")
		},
		"fabricated confirmation actor": func(t *testing.T, candidate map[string]any) {
			request := map830G3(t, candidate["request"])
			confirmation := map830G3(t, request["profile_confirmation"])
			receipt := map830G3(t, confirmation["receipt"])
			receipt["actor"] = "fabricated-reviewer"
			digest, err := batchConceptHash830G3("830-g3-profile-user-confirmation.v1", receipt)
			require.NoError(t, err)
			confirmation["receipt_semantic_sha256"] = digest
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			candidate := fixtureMap830G3(t)
			mutate(t, candidate)
			_, err := ParseBatchConceptCandidateBundle830G3(rehashCandidateMap830G3(t, candidate))
			require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
		})
	}
}

func TestBatchConceptTypedText830G3AllowsBodiesButRejectsStructuredControls(t *testing.T) {
	require.True(t, validBodyText830G3("第一行\n第二行\t值\r尾"))
	for _, value := range []string{"bad\nid", "bad\tid", "bad\rid", "bad\x7fid"} {
		require.False(t, validStructuredText830G3(value))
	}
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, decodeExactObject830G3(raw, &bundle, batchBundleKeys830G3, true))
	typed, err := decodeResolutionInputs830G3(bundle.Request.ResolutionInputs, bundle.Request.Resolution)
	require.NoError(t, err)
	receipt := typed.Proposals.ModelReceipts[0].PolicyReceipt
	receipt.RunID = "bad\nrun"
	require.ErrorIs(t, validatePolicyReceipt830G3(receipt), ErrConceptCandidateBundle830G3)
}

func TestBatchPolicyReceipt830G3UserGeminiGateway(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, decodeExactObject830G3(raw, &bundle, batchBundleKeys830G3, true))
	typed, err := decodeResolutionInputs830G3(bundle.Request.ResolutionInputs, bundle.Request.Resolution)
	require.NoError(t, err)
	original := typed.Proposals.ModelReceipts[0].PolicyReceipt
	require.NoError(t, validatePolicyReceipt830G3(original))
	require.NotNil(t, original.PermitView)
	identity := ModelIdentity830G3{
		Provider: "g3-user-gateway", DeploymentID: "gemini-3.7-flash-medium",
		Family: "gemini", Role: "classify", PolicyVersion: "g3-user-gemini-gateway-v1",
	}
	makeReceipt := func(id ModelIdentity830G3) ModelPolicyReceipt830G3 {
		receipt := original
		view := *original.PermitView
		view.Identity = id
		receipt.PermitView = &view
		receipt.IdentityKey = []string{id.Provider, id.DeploymentID, id.Family, id.Role, id.PolicyVersion}
		digest, digestErr := permitDigest830G3(view)
		require.NoError(t, digestErr)
		receipt.PermitDigest = &digest
		return receipt
	}
	t.Run("exact user gateway accepted", func(t *testing.T) {
		require.NoError(t, validatePolicyReceipt830G3(makeReceipt(identity)))
	})
	for _, field := range []string{"provider", "deployment", "policy", "role"} {
		t.Run("rehashed wrong "+field+" rejected", func(t *testing.T) {
			changed := identity
			switch field {
			case "provider":
				changed.Provider = "other-gateway"
			case "deployment":
				changed.DeploymentID = "gemini-3.7-flash-high"
			case "policy":
				changed.PolicyVersion = "other-policy"
			case "role":
				changed.Role = "extract"
			}
			require.ErrorIs(t, validatePolicyReceipt830G3(makeReceipt(changed)), ErrConceptCandidateBundle830G3)
		})
	}
	t.Run("identity key drift rejected", func(t *testing.T) {
		receipt := makeReceipt(identity)
		receipt.IdentityKey[0] = "other-gateway"
		require.ErrorIs(t, validatePolicyReceipt830G3(receipt), ErrConceptCandidateBundle830G3)
	})
}

func TestBatchConceptCanonical830G3PreservesMultilineAndRejectsBadDomain(t *testing.T) {
	payload := map[string]any{"body": "first\nsecond\tvalue\rline"}
	digest, err := batchConceptHash830G3("batch-test.830.g3.v1", payload)
	require.NoError(t, err)
	require.Equal(t, "6fd2a4f372f2f7f93080180728eedacbd5cb00b349009241f1332760076efeef", digest)

	for _, domain := range []string{"", "批次", "bad\nkind"} {
		_, err := batchConceptHash830G3(domain, payload)
		require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
	}
}

func TestBatchConceptCanonical830G3PreservesExactUnicodeBodyScalars(t *testing.T) {
	body := "保险\uf99c表"
	source := ConceptSourceBlock830G2{Text: body}
	_, err := batchConceptHash830G3("compile-request.830.g2.v1", struct {
		Sources []ConceptSourceBlock830G2 `json:"sources"`
	}{Sources: []ConceptSourceBlock830G2{source}})
	require.NoError(t, err)

	evidence := ConceptEvidence830G2{Quote: body}
	definition := ConceptDefinition830G2{SpaceID: "space", CanonicalKey: "key", SenseKey: "sense", Evidence: []ConceptEvidence830G2{evidence}}
	payload, err := json.Marshal(definition)
	require.NoError(t, err)
	id, err := conceptDefinitionID830G2(definition)
	require.NoError(t, err)
	member := ConceptPageMember830G2{Kind: "concept", MemberID: id, OwnerID: definition.SpaceID, Payload: payload}
	_, err = batchConceptHash830G3("batch-concept-member.830.g3.v1", member)
	require.NoError(t, err)
	var payloadMap map[string]any
	require.NoError(t, json.Unmarshal(payload, &payloadMap))
	payloadMap["unexpected"] = true
	extraPayload, err := json.Marshal(payloadMap)
	require.NoError(t, err)
	member.Payload = extraPayload
	_, err = batchConceptHash830G3("batch-concept-member.830.g3.v1", member)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
	member.Kind, member.Payload = "entity_overview", payload
	_, err = batchConceptHash830G3("batch-concept-member.830.g3.v1", member)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
}

func TestBatchConceptCanonical830G3RequiresPairedRawOutput(t *testing.T) {
	body := "保险\uf99c表"
	output := ConceptCompileOutput830G2{
		Contract:    "concept-compile-output.830.g2.v1",
		Definitions: []ConceptDefinition830G2{{Evidence: []ConceptEvidence830G2{{Quote: body}}}},
		Fields:      []ConceptFieldAssertion830G2{}, Pages: []ConceptFreeWikiPage830G2{},
		Audit: []ConceptAuditDisposition830G2{}, Transformation: "EXTRACT",
	}
	rawOutput, err := batchConceptCanonicalJSON830G3(output)
	require.NoError(t, err)
	result := ConceptCompileResult830G2{
		Output: output,
		Execution: ConceptExecutionRecord830G2{
			RunID: "run", Implementation: "implementation", ContextHash: strings.Repeat("a", 64),
			RawOutput: string(rawOutput), RawOutputHash: sha256Hex830G3(rawOutput),
		},
	}
	digest, err := batchConceptHash830G3("paired-result-test.830.g3.v1", result)
	require.NoError(t, err)
	require.Regexp(t, "^[0-9a-f]{64}$", digest)

	_, err = batchConceptHash830G3("batch-concept-model-execution.830.g3.v1", result.Execution)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
	tampered := result
	tampered.Execution.RawOutput += " "
	_, err = batchConceptHash830G3("paired-result-test.830.g3.v1", tampered)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
}

func TestParseBatchConceptCandidateBundle830G3PythonUnicodeParity(t *testing.T) {
	path := os.Getenv("G3_UNICODE_CANDIDATE")
	if path == "" {
		t.Skip("set G3_UNICODE_CANDIDATE to the frozen Python U+F99C candidate")
	}
	raw, err := os.ReadFile(path)
	require.NoError(t, err)
	var decoded BatchConceptCandidateBundle830G3
	require.NoError(t, decodeExactObject830G3(raw, &decoded, batchBundleKeys830G3, true))
	require.NoError(t, validateBatchRequest830G3(decoded.Request))
	require.NoError(t, validateDelta830G3(decoded.Request, decoded.ModelCompileResult.Output))
	require.NoError(t, validateBatchConceptBundle830G3(decoded))
	bundle, canonical, err := CanonicalBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	require.Equal(t, raw, canonical)
	require.Equal(t, "e18445f35088ab02888b9a8bc2d5f86f07d7e3dc2282b171d8451f1097e12a93", bundle.CandidateHash)
	require.Equal(t, "9390bb31", bundle.Request.RequestSHA256[:8])
	require.Len(t, bundle.PageManifest.Members, 354)
	baseRequestHash, err := compileRequestHash830G3(bundle.Request.BaseRequest)
	require.NoError(t, err)
	require.Equal(t, "f079e4b96087b6d9a53adc753e277066ce15647f69b97ead92dd59e846176bf4", baseRequestHash)
	modelOutputHash, err := compileOutputHash830G3(bundle.ModelCompileResult.Output)
	require.NoError(t, err)
	require.Equal(t, "59ae1ffedfee830e4d9da766c4a1351856e58d09b0a20acfdf11a7413ba14e28", modelOutputHash)
	compileOutputHash, err := compileOutputHash830G3(bundle.CompileResult.Output)
	require.NoError(t, err)
	require.Equal(t, "606a21c700dff76856c629ce4e838676105b3ba4572b22327693549d60effc20", compileOutputHash)
	modelExecutionHash, err := pairedExecutionHash830G3(
		"batch-concept-model-execution.830.g3.v1", bundle.ModelCompileResult,
	)
	require.NoError(t, err)
	require.Equal(t, "137e83c31a8c3d06dd1575f1eec80a7c6bc4b9b0afcbadef22aeee996e45edc0", modelExecutionHash)
	reviewExecutionHash, err := pairedExecutionHash830G3(
		"batch-concept-review-execution.830.g3.v1", bundle.ReviewResult,
	)
	require.NoError(t, err)
	require.Equal(t, "5cadc4e78f3f5c000fb81595539dde2a0a5779376731240fd75422a21cbbda50", reviewExecutionHash)
	for _, member := range bundle.PageManifest.Members {
		if member.MemberID != "assertion_a83c62ffffec835c29eca5e46ab26c194132dfa827c3b1f148898295a19ddc62" {
			continue
		}
		memberHash, hashErr := batchConceptHash830G3("batch-concept-member.830.g3.v1", member)
		require.NoError(t, hashErr)
		require.Equal(t, "b5760c4bad23c73c044dc305657f2b0e2d2cc9957ca4110b148689f54b04c8d7", memberHash)
		return
	}
	t.Fatal("Python U+F99C candidate lacks the frozen parity member")
}

func TestBatchConceptPreparationActual342FitsExistingEightMiBLimit(t *testing.T) {
	raw, err := os.ReadFile(batchConceptPreparation830G3)
	require.NoError(t, err)
	require.Equal(t, 2_254_490, len(raw))
	require.Less(t, len(raw), 8*1024*1024)
}

func TestBatchConceptCanonical830G3PreservesTypedBusinessText(t *testing.T) {
	body := "原文\uf99c\n条件"
	values := []any{
		ConceptDefinition830G2{Title: body, Body: body},
		ConceptFieldAssertion830G2{Value: &body, UnknownReason: &body, Conditions: []string{body}, Exceptions: []string{body}, ValidTime: body},
		ConceptFreeWikiPage830G2{Title: body, Body: body, Conditions: []string{body}, Exceptions: []string{body}, ValidTime: body},
		ConceptAuditDisposition830G2{Reason: body},
		ConceptReviewOutput830G2{Reasons: []string{body}},
	}
	for _, value := range values {
		raw, err := batchConceptCanonicalJSON830G3(value)
		require.NoError(t, err, "%T", value)
		require.Contains(t, string(raw), "\uf99c")
	}
	for _, value := range []any{
		map[string]any{"body": body}, ConceptDefinition830G2{CanonicalKey: body},
		ConceptDefinition830G2{Aliases: []string{body}}, ConceptFieldAssertion830G2{EntityVersion: body},
		ConceptAuditDisposition830G2{Key: body}, ConceptReviewOutput830G2{Decision: body},
		ConceptDefinition830G2{Body: "bad\x00"}, ConceptFieldAssertion830G2{Conditions: []string{"bad\x7f"}},
	} {
		_, err := batchConceptCanonicalJSON830G3(value)
		require.ErrorIs(t, err, ErrConceptCandidateBundle830G3, "%T", value)
	}
	type unrelatedDefinition ConceptDefinition830G2
	_, err := batchConceptCanonicalJSON830G3(unrelatedDefinition{Body: body})
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
}

func TestBatchConceptCanonical830G3BusinessMemberProjectionClosure(t *testing.T) {
	body := "原文\uf99c"
	for _, fixture := range []struct {
		kind, title, content string
		payload              any
	}{
		{"concept", body, body, ConceptDefinition830G2{SpaceID: "space", CanonicalKey: "key", SenseKey: "sense", Title: body, Body: body}},
		{"field_assertion", "field", body, ConceptFieldAssertion830G2{SpaceID: "space", EntityID: "entity", FieldKey: "field", Value: &body}},
		{"field_assertion", "field", "未知：" + body, ConceptFieldAssertion830G2{SpaceID: "space", EntityID: "entity", FieldKey: "field", UnknownReason: &body}},
		{"free_wiki_item", body, body, ConceptFreeWikiPage830G2{SpaceID: "space", EntityID: "entity", StableKey: "page", Title: body, Body: body}},
	} {
		payload, err := json.Marshal(fixture.payload)
		require.NoError(t, err)
		member := ConceptPageMember830G2{Kind: fixture.kind, Title: fixture.title, Content: fixture.content, Payload: payload}
		switch value := fixture.payload.(type) {
		case ConceptDefinition830G2:
			member.MemberID, err = conceptDefinitionID830G2(value)
			member.OwnerID = value.SpaceID
		case ConceptFieldAssertion830G2:
			member.MemberID, err = conceptFieldID830G2(value)
			member.OwnerID = value.EntityID
		case ConceptFreeWikiPage830G2:
			member.MemberID, err = conceptFreePageID830G2(value)
			member.OwnerID = value.EntityID
		}
		require.NoError(t, err)
		_, err = batchConceptCanonicalJSON830G3(member)
		require.NoError(t, err, fixture.kind)
		member.Content += "tampered"
		_, err = batchConceptCanonicalJSON830G3(member)
		require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
	}
	_, err := batchConceptCanonicalJSON830G3(ConceptPageMember830G2{Kind: "entity_overview", Title: body, Payload: json.RawMessage(`{"member_ids":[]}`)})
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G3)
}

func TestBatchConceptDefinitionHash830G3RetainsBusinessText(t *testing.T) {
	definition := ConceptDefinition830G2{SpaceID: "space", CanonicalKey: "key", SenseKey: "sense", Title: "原文\uf99c", Body: "正文\uf99c", Evidence: []ConceptEvidence830G2{}, Aliases: []string{}, Origin: "model"}
	digest, err := conceptDefinitionHash830G3(definition)
	require.NoError(t, err)
	definition.Aliases = []string{"alias"}
	again, err := conceptDefinitionHash830G3(definition)
	require.NoError(t, err)
	require.Equal(t, digest, again)
	definition.Body += "changed"
	changed, err := conceptDefinitionHash830G3(definition)
	require.NoError(t, err)
	require.NotEqual(t, digest, changed)
}

func TestBatchConceptBusinessText830G3PythonParity(t *testing.T) {
	path := os.Getenv("G3_BUSINESS_TEXT_PARITY")
	if path == "" {
		t.Skip("set G3_BUSINESS_TEXT_PARITY to the generated typed Python parity cases")
	}
	raw, err := os.ReadFile(path)
	require.NoError(t, err)
	var rows []struct {
		Kind           string          `json:"kind"`
		Wire           json.RawMessage `json:"wire"`
		SHA256         string          `json:"sha256"`
		DefinitionHash string          `json:"definition_hash"`
	}
	require.NoError(t, json.Unmarshal(raw, &rows))
	require.GreaterOrEqual(t, len(rows), 8)
	for _, row := range rows {
		var target any
		switch row.Kind {
		case "definition":
			target = &ConceptDefinition830G2{}
		case "field":
			target = &ConceptFieldAssertion830G2{}
		case "page":
			target = &ConceptFreeWikiPage830G2{}
		case "audit":
			target = &ConceptAuditDisposition830G2{}
		case "review":
			target = &ConceptReviewOutput830G2{}
		case "member":
			target = &ConceptPageMember830G2{}
		default:
			t.Fatalf("unexpected parity type %q", row.Kind)
		}
		require.NoError(t, strictConceptDecode830G2(row.Wire, target))
		canonical, err := batchConceptCanonicalJSON830G3(target)
		require.NoError(t, err, row.Kind)
		require.Equal(t, row.SHA256, sha256Hex830G3(canonical), row.Kind)
		if definition, ok := target.(*ConceptDefinition830G2); ok {
			hash, err := conceptDefinitionHash830G3(*definition)
			require.NoError(t, err)
			require.Equal(t, row.DefinitionHash, hash)
		}
	}
}

func TestBatchConcept830G3DerivesFieldCountsFromRequest(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, decodeExactObject830G3(raw, &bundle, batchBundleKeys830G3, true))
	request := bundle.Request
	output := bundle.ModelCompileResult.Output
	extra := output.Fields[0]
	extra.FieldKey = "additional_required_field"
	request.BaseRequest.RequiredFields[extra.EntityID] = append(request.BaseRequest.RequiredFields[extra.EntityID], extra.FieldKey)
	output.RequestHash, err = compileRequestHash830G3(request.BaseRequest)
	require.NoError(t, err)
	output.Fields = append(output.Fields, extra)
	id, err := conceptFieldID830G2(extra)
	require.NoError(t, err)
	output.Audit = append(output.Audit, ConceptAuditDisposition830G2{Key: id, Disposition: "field_rule", Reason: "request requires this field"})
	require.NoError(t, validateDelta830G3(request, output))
	composed, err := composeBatchOutput830G3(request, output)
	require.NoError(t, err)
	require.Len(t, composed.Fields, 343)
	missing := output
	missing.Fields = output.Fields[:len(output.Fields)-1]
	require.Error(t, validateDelta830G3(request, missing))
	duplicate := output
	duplicate.Fields = append(append([]ConceptFieldAssertion830G2{}, output.Fields...), extra)
	require.Error(t, validateDelta830G3(request, duplicate))
	foreign := output
	foreign.Fields = append([]ConceptFieldAssertion830G2{}, output.Fields...)
	foreign.Fields[len(foreign.Fields)-1].FieldKey = "not_required"
	require.Error(t, validateDelta830G3(request, foreign))
}

func TestBatchConcept830G3AcceptsProjectedNovelPageCount(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, decodeExactObject830G3(raw, &bundle, batchBundleKeys830G3, true))
	output := bundle.CompileResult.Output
	page := output.Pages[0]
	page.StableKey += "-novel"
	id, err := conceptFreePageID830G2(page)
	require.NoError(t, err)
	output.Pages = append(output.Pages, page)
	output.Audit = append(output.Audit, ConceptAuditDisposition830G2{Key: id, Disposition: "new_page", Reason: "supported new page"})
	manifest, err := projectBatchMembers830G3(bundle.Request, output)
	require.NoError(t, err)
	require.Len(t, manifest.Members, 355)
	require.NoError(t, validatePageManifest830G3(bundle.Request, output, manifest))
	manifest.Members = manifest.Members[:len(manifest.Members)-1]
	require.Error(t, validatePageManifest830G3(bundle.Request, output, manifest))
}

func TestBatchConcept830G3PythonNovelPageCandidate(t *testing.T) {
	path := os.Getenv("G3_NOVEL_PAGE_CANDIDATE")
	if path == "" {
		t.Skip("set G3_NOVEL_PAGE_CANDIDATE to the valid Python novel-page Candidate")
	}
	raw, err := os.ReadFile(path)
	require.NoError(t, err)
	bundle, canonical, err := CanonicalBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	require.Equal(t, raw, canonical)
	require.Greater(t, len(bundle.ModelCompileResult.Output.Pages), 0)
	require.Greater(t, len(bundle.PageManifest.Members), 354)
}

func TestBatchNavigationAssignment830G3LegacyHashProjection(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(raw, &bundle))
	projected, err := batchConceptRootWithout830G3(reflect.ValueOf(bundle), "candidate_hash")
	require.NoError(t, err)
	require.NotContains(t, projected, "navigation_assignments", "omitted metadata must also be absent from the hash preimage")
	expected, err := batchConceptHash830G3(bundle.Contract, projected)
	require.NoError(t, err)
	require.Equal(t, bundle.CandidateHash, expected)
}

func TestBatchNavigationAssignment830G3ExactCarryAllowsOrdinaryCompilation(t *testing.T) {
	parent, child, row := navigationFixture830G3(t)
	child.ModelCompileResult.Execution.Implementation = "ordinary-model-compiler"
	require.NoError(t, validateNavigationAssignments830G3(child), "structural validation cannot infer parent history")
	require.Error(t, ValidateBatchNavigationHistory830G3(parent, child), "new navigation needs identity reuse")
	parent.NavigationAssignments = []NavigationAssignment830G3{row}
	child.CompileResult.Output.Fields = append([]ConceptFieldAssertion830G2(nil), child.CompileResult.Output.Fields...)
	child.CompileResult.Output.Fields = child.CompileResult.Output.Fields[:len(child.CompileResult.Output.Fields)-1]
	require.NoError(t, ValidateBatchNavigationHistory830G3(parent, child), "exact display carry leaves content eligibility to normal compilation validation")
	row.AssignmentVersion++
	row.PreviousAssignmentSHA256 = row.AssignmentSHA256
	row.AssignmentSHA256, _ = batchConceptHashWithout830G3(row.Contract, row, "assignment_sha256")
	child.NavigationAssignments = []NavigationAssignment830G3{row}
	require.Error(t, ValidateBatchNavigationHistory830G3(parent, child), "changed navigation cannot ride ordinary compilation")
}

func TestBatchNavigationAssignment830G3RejectsCompleteBindingDrift(t *testing.T) {
	parent, basis, _ := navigationFixture830G3(t)
	for name, mutate := range map[string]func(*EntityCompileBinding830G3){
		"display identity": func(binding *EntityCompileBinding830G3) { binding.DisplayName += "修订" },
		"entity identity":  func(binding *EntityCompileBinding830G3) { binding.EntityKeySHA256 = strings.Repeat("a", 64) },
		"resolution reference": func(binding *EntityCompileBinding830G3) {
			binding.ResolutionRefs[0].ClassificationAssignmentSHA256 = strings.Repeat("b", 64)
		},
		"resolution evidence": func(binding *EntityCompileBinding830G3) { binding.ResolutionEvidence[0].Evidence.Quote += "修订" },
		"source association": func(binding *EntityCompileBinding830G3) {
			binding.SourceMaterialIDs = append(binding.SourceMaterialIDs, "extra-material")
		},
	} {
		t.Run(name, func(t *testing.T) {
			child := basis
			raw, err := json.Marshal(basis.Request.EntityBindings)
			require.NoError(t, err)
			child.Request.EntityBindings = nil
			require.NoError(t, json.Unmarshal(raw, &child.Request.EntityBindings))
			binding := &child.Request.EntityBindings[0]
			require.NotEmpty(t, binding.ResolutionRefs)
			require.NotEmpty(t, binding.ResolutionEvidence)
			mutate(binding)
			binding.BindingSHA256, err = batchConceptHashWithout830G3(binding.Contract, *binding, "binding_sha256")
			require.NoError(t, err)
			require.Error(t, ValidateBatchNavigationHistory830G3(parent, child), "rehashing an altered binding cannot authorize a navigation-only update")
		})
	}
}
