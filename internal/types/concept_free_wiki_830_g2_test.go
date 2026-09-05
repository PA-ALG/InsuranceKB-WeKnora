package types

import (
	"bytes"
	"encoding/json"
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

func conceptVector830G2(t *testing.T) []byte {
	t.Helper()
	raw, err := os.ReadFile("../../harness/tests/fixtures/concept_free_wiki_830_g2_contract_vector.json")
	require.NoError(t, err)
	return raw
}

func mutateConceptVector830G2(t *testing.T, mutate func(map[string]any)) []byte {
	t.Helper()
	var value map[string]any
	require.NoError(t, json.Unmarshal(conceptVector830G2(t), &value))
	mutate(value)
	raw, err := json.Marshal(value)
	require.NoError(t, err)
	return raw
}

func object830G2(t *testing.T, value any, key string) map[string]any {
	t.Helper()
	result, ok := value.(map[string]any)[key].(map[string]any)
	require.True(t, ok)
	return result
}

func arrayObject830G2(t *testing.T, value any, key string, index int) map[string]any {
	t.Helper()
	items, ok := value.(map[string]any)[key].([]any)
	require.True(t, ok)
	result, ok := items[index].(map[string]any)
	require.True(t, ok)
	return result
}

func TestParseConceptCandidateBundle830G2ProjectsFrozenVector(t *testing.T) {
	bundle, err := ParseConceptCandidateBundle830G2(conceptVector830G2(t))
	require.NoError(t, err)
	require.Equal(t, "57ef3c1044874555a85330fbf7cc8505611c3211a5284ff17f0edf97f945dee5", bundle.CandidateHash)
	require.Len(t, bundle.CompileResult.Output.Fields, 2)
	require.Equal(t, "present", bundle.CompileResult.Output.Fields[0].State)
	require.Equal(t, "unknown", bundle.CompileResult.Output.Fields[1].State)
	require.Len(t, bundle.CompileResult.Output.Pages, 1)
	definition := bundle.CompileResult.Output.Definitions[0]
	definitionID, err := definition.DefinitionID()
	require.NoError(t, err)
	require.Equal(t, "concept_c730e23edec4bc4fa3035b05ad32ddffb0a0e38a841fff3c58a0eef88cdcc4b3", definitionID)
	definitionHash, err := definition.DefinitionHash()
	require.NoError(t, err)
	require.Equal(t, "7b0d4bb6e129032821c3b3d15a59cfb97501ce4872d25475e6e255faff64e6ad", definitionHash)
	aggregateHash, err := ConceptAggregateHash830G2(
		"release-test", 1, definition, bundle.CompileResult.Output.Fields,
	)
	require.NoError(t, err)
	require.Equal(t, "2ca064c065930da3717944cbad5eb8a95a928bdaf633704136ef5f46ffdab457", aggregateHash)

	snapshots, err := bundle.SnapshotMembers()
	require.NoError(t, err)
	require.Len(t, snapshots, 6)
	for index, snapshot := range snapshots {
		require.Equal(t, bundle.PageManifest.Members[index].Kind, snapshot.Kind)
		require.Equal(t, bundle.PageManifest.Members[index].MemberID, snapshot.LogicalSlug)
		require.Equal(t, bundle.CandidateHash, snapshot.RevisionID)
		require.Regexp(t, "^[0-9a-f]{64}$", snapshot.MemberDigest)
		require.JSONEq(t, string(bundle.PageManifest.Members[index].Payload), string(snapshot.Payload))
	}
}

func TestParseConceptCandidateBundle830G2RejectsSourceScopeAndExistingSnapshotDrift(t *testing.T) {
	tests := map[string]func(map[string]any){
		"source tenant": func(value map[string]any) {
			request := object830G2(t, value, "request")
			arrayObject830G2(t, request, "sources", 0)["tenant_id"] = float64(2)
		},
		"source space": func(value map[string]any) {
			request := object830G2(t, value, "request")
			arrayObject830G2(t, request, "sources", 0)["space_id"] = "space-b"
		},
		"entity version coverage": func(value map[string]any) {
			request := object830G2(t, value, "request")
			request["entity_versions"] = map[string]any{"entity-b": "v1"}
		},
		"output entity version": func(value map[string]any) {
			output := object830G2(t, object830G2(t, value, "compile_result"), "output")
			arrayObject830G2(t, output, "fields", 0)["entity_version"] = "v2"
		},
		"existing page entity missing": func(value map[string]any) {
			request := object830G2(t, value, "request")
			output := object830G2(t, object830G2(t, value, "compile_result"), "output")
			request["existing_pages"] = []any{arrayObject830G2(t, output, "pages", 0)}
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			_, err := ParseConceptCandidateBundle830G2(mutateConceptVector830G2(t, mutate))
			require.ErrorIs(t, err, ErrConceptCandidateBundle830G2)
		})
	}
}

func TestParseConceptCandidateBundle830G2RejectsUnknownKey(t *testing.T) {
	raw := mutateConceptVector830G2(t, func(value map[string]any) { value["unexpected"] = true })
	_, err := ParseConceptCandidateBundle830G2(raw)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G2)
}

func TestParseConceptCandidateBundle830G2RejectsNestedDuplicateKeys(t *testing.T) {
	raw := conceptVector830G2(t)
	tampered := bytes.Replace(
		raw,
		[]byte(`"policy_identity": "g2-initial-80-60.v1"`),
		[]byte(`"policy_identity": "g2-initial-80-60.v1", "policy_identity": "g2-initial-80-60.v1"`),
		1,
	)
	require.NotEqual(t, string(raw), string(tampered))

	_, err := ParseConceptCandidateBundle830G2(tampered)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G2)
}

func TestParseConceptCandidateBundle830G2RejectsCaseFoldedJSONKeys(t *testing.T) {
	raw := conceptVector830G2(t)
	for name, replacement := range map[string][]byte{
		"case alias only":      []byte(`"TENANT_ID": 1,`),
		"exact and case alias": []byte(`"tenant_id": 1, "TENANT_ID": 1,`),
	} {
		t.Run(name, func(t *testing.T) {
			tampered := bytes.Replace(raw, []byte(`"tenant_id": 1,`), replacement, 1)
			require.NotEqual(t, string(raw), string(tampered))

			_, err := ParseConceptCandidateBundle830G2(tampered)
			require.ErrorIs(t, err, ErrConceptCandidateBundle830G2)
		})
	}
}

func TestParseConceptCandidateBundle830G2RejectsForeignSpaceAndDanglingConcept(t *testing.T) {
	tests := map[string]func(map[string]any){
		"foreign space": func(value map[string]any) {
			output := object830G2(t, object830G2(t, value, "compile_result"), "output")
			arrayObject830G2(t, output, "fields", 0)["space_id"] = "space-b"
		},
		"dangling concept": func(value map[string]any) {
			output := object830G2(t, object830G2(t, value, "compile_result"), "output")
			arrayObject830G2(t, output, "fields", 0)["concept_ids"] = []any{"concept_missing"}
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			_, err := ParseConceptCandidateBundle830G2(mutateConceptVector830G2(t, mutate))
			require.ErrorIs(t, err, ErrConceptCandidateBundle830G2)
		})
	}
}

func TestParseConceptCandidateBundle830G2RejectsMissingOrStaleReview(t *testing.T) {
	tests := map[string]func(map[string]any){
		"no review": func(value map[string]any) { delete(value, "review_result") },
		"not approved": func(value map[string]any) {
			review := object830G2(t, object830G2(t, value, "review_result"), "output")
			review["decision"] = "NEEDS_HUMAN"
		},
		"same execution": func(value map[string]any) {
			compile := object830G2(t, object830G2(t, value, "compile_result"), "execution")
			review := object830G2(t, object830G2(t, value, "review_result"), "execution")
			review["run_id"] = compile["run_id"]
		},
		"missing admission score": func(value map[string]any) {
			review := object830G2(t, object830G2(t, value, "review_result"), "output")
			review["page_scores"] = map[string]any{}
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			_, err := ParseConceptCandidateBundle830G2(mutateConceptVector830G2(t, mutate))
			require.ErrorIs(t, err, ErrConceptCandidateBundle830G2)
		})
	}
}

func TestParseConceptCandidateBundle830G2RejectsInvalidStateSourceAndRawBinding(t *testing.T) {
	tests := map[string]func(map[string]any){
		"unknown has value": func(value map[string]any) {
			output := object830G2(t, object830G2(t, value, "compile_result"), "output")
			arrayObject830G2(t, output, "fields", 1)["value"] = "invented"
		},
		"quote drift": func(value map[string]any) {
			output := object830G2(t, object830G2(t, value, "compile_result"), "output")
			definition := arrayObject830G2(t, output, "definitions", 0)
			arrayObject830G2(t, definition, "evidence", 0)["quote"] = "unsupported"
		},
		"source revision drift": func(value map[string]any) {
			output := object830G2(t, object830G2(t, value, "compile_result"), "output")
			definition := arrayObject830G2(t, output, "definitions", 0)
			arrayObject830G2(t, definition, "evidence", 0)["revision_id"] = "r2"
		},
		"raw output drift": func(value map[string]any) {
			execution := object830G2(t, object830G2(t, value, "compile_result"), "execution")
			execution["raw_output"] = "{}"
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			_, err := ParseConceptCandidateBundle830G2(mutateConceptVector830G2(t, mutate))
			require.ErrorIs(t, err, ErrConceptCandidateBundle830G2)
		})
	}
}

func TestParseConceptCandidateBundle830G2RejectsPageManifestTamper(t *testing.T) {
	raw := mutateConceptVector830G2(t, func(value map[string]any) {
		manifest := object830G2(t, value, "page_manifest")
		arrayObject830G2(t, manifest, "members", 0)["content"] = "tampered"
	})
	_, err := ParseConceptCandidateBundle830G2(raw)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G2)
}

func TestParseConceptCandidateBundle830G2RejectsAuditMemberDrift(t *testing.T) {
	raw := mutateConceptVector830G2(t, func(value map[string]any) {
		output := object830G2(t, object830G2(t, value, "compile_result"), "output")
		arrayObject830G2(t, output, "audit", 0)["key"] = "concept_missing"
	})
	_, err := ParseConceptCandidateBundle830G2(raw)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G2)
}
