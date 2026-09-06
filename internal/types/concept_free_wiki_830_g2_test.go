package types

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

func conceptCanonicalVector830G2(t *testing.T) struct {
	HashPrefixHex string `json:"hash_prefix_hex"`
	ValidCases    []struct {
		Name             string         `json:"name"`
		Kind             string         `json:"kind"`
		Payload          map[string]any `json:"payload"`
		CanonicalJSONHex string         `json:"canonical_json_hex"`
		ExpectedSHA256   string         `json:"expected_sha256"`
	} `json:"valid_cases"`
	InvalidCases []struct {
		Name    string         `json:"name"`
		Payload map[string]any `json:"payload"`
	} `json:"invalid_cases"`
	RealA struct {
		SourceBlock          ConceptSourceBlock830G2    `json:"source_block"`
		SourceTextCodepoints int                        `json:"source_text_codepoints"`
		SourceTextLineFeeds  int                        `json:"source_text_line_feeds"`
		CompileRequest       ConceptCompileRequest830G2 `json:"compile_request"`
		CompileRequestSHA256 string                     `json:"compile_request_sha256"`
	} `json:"real_a_source"`
	Multiline struct {
		Bundle               json.RawMessage `json:"bundle"`
		MembersHash          string          `json:"members_hash"`
		CandidateHash        string          `json:"candidate_hash"`
		SnapshotMemberSHA256 []string        `json:"snapshot_member_sha256"`
	} `json:"multiline_bundle"`
	LegacyBundleRequestSHA256 string `json:"legacy_bundle_request_sha256"`
} {
	t.Helper()
	raw, err := os.ReadFile("../../harness/tests/fixtures/concept_free_wiki_830_g2_canonical_vector.json")
	require.NoError(t, err)
	var vector struct {
		HashPrefixHex string `json:"hash_prefix_hex"`
		ValidCases    []struct {
			Name             string         `json:"name"`
			Kind             string         `json:"kind"`
			Payload          map[string]any `json:"payload"`
			CanonicalJSONHex string         `json:"canonical_json_hex"`
			ExpectedSHA256   string         `json:"expected_sha256"`
		} `json:"valid_cases"`
		InvalidCases []struct {
			Name    string         `json:"name"`
			Payload map[string]any `json:"payload"`
		} `json:"invalid_cases"`
		RealA struct {
			SourceBlock          ConceptSourceBlock830G2    `json:"source_block"`
			SourceTextCodepoints int                        `json:"source_text_codepoints"`
			SourceTextLineFeeds  int                        `json:"source_text_line_feeds"`
			CompileRequest       ConceptCompileRequest830G2 `json:"compile_request"`
			CompileRequestSHA256 string                     `json:"compile_request_sha256"`
		} `json:"real_a_source"`
		Multiline struct {
			Bundle               json.RawMessage `json:"bundle"`
			MembersHash          string          `json:"members_hash"`
			CandidateHash        string          `json:"candidate_hash"`
			SnapshotMemberSHA256 []string        `json:"snapshot_member_sha256"`
		} `json:"multiline_bundle"`
		LegacyBundleRequestSHA256 string `json:"legacy_bundle_request_sha256"`
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	require.NoError(t, decoder.Decode(&vector))
	return vector
}

func TestConceptCanonical830G2AllowsSourceTextControlsAndRealARequest(t *testing.T) {
	vector := conceptCanonicalVector830G2(t)
	for _, testCase := range vector.ValidCases {
		t.Run(testCase.Name, func(t *testing.T) {
			hash, err := conceptDigest830G2(testCase.Kind, testCase.Payload)
			require.NoError(t, err)
			require.Equal(t, testCase.ExpectedSHA256, hash)
		})
	}
	require.Equal(t, vector.RealA.SourceTextCodepoints, len([]rune(vector.RealA.SourceBlock.Text)))
	require.Equal(t, vector.RealA.SourceTextLineFeeds, bytes.Count([]byte(vector.RealA.SourceBlock.Text), []byte("\n")))
	hash, err := conceptDigest830G2("compile-request", vector.RealA.CompileRequest)
	require.NoError(t, err)
	require.Equal(t, vector.RealA.CompileRequestSHA256, hash)

	bundle, err := ParseConceptCandidateBundle830G2(vector.Multiline.Bundle)
	require.NoError(t, err)
	require.Equal(t, vector.Multiline.MembersHash, bundle.PageManifest.MembersHash)
	require.Equal(t, vector.Multiline.CandidateHash, bundle.CandidateHash)
	snapshots, err := bundle.SnapshotMembers()
	require.NoError(t, err)
	require.Len(t, snapshots, len(vector.Multiline.SnapshotMemberSHA256))
	for index := range snapshots {
		require.Equal(t, vector.Multiline.SnapshotMemberSHA256[index], snapshots[index].MemberDigest)
	}
}

func TestConceptCanonical830G2KeepsOldBundleHashAndRejectsAmbiguousValues(t *testing.T) {
	vector := conceptCanonicalVector830G2(t)
	for _, testCase := range vector.InvalidCases {
		t.Run(testCase.Name, func(t *testing.T) {
			_, err := conceptDigest830G2("canonical-vector", testCase.Payload)
			require.Error(t, err)
		})
	}
	var old struct {
		Request ConceptCompileRequest830G2 `json:"request"`
	}
	require.NoError(t, json.Unmarshal(conceptVector830G2(t), &old))
	hash, err := conceptDigest830G2("compile-request", old.Request)
	require.NoError(t, err)
	require.Equal(t, vector.LegacyBundleRequestSHA256, hash)
	for _, invalidIdentity := range []string{"native\tv1", "native\rv1", "native\nv1", "native\x00v1", "native\x7fv1"} {
		require.False(t, conceptIdentity830G2(invalidIdentity), "identity %q contains a control character", invalidIdentity)
	}
}

func TestConceptCanonical830G2RejectsInvalidUTF8AndUnpairedSurrogates(t *testing.T) {
	type wire struct {
		Value string `json:"value"`
	}
	invalidUTF8 := append([]byte(`{"value":"`), 0xff)
	invalidUTF8 = append(invalidUTF8, []byte(`"}`)...)
	for name, raw := range map[string][]byte{
		"invalid utf8":        invalidUTF8,
		"lone high surrogate": []byte(`{"value":"\ud800"}`),
		"lone low surrogate":  []byte(`{"value":"\udc00"}`),
	} {
		t.Run(name, func(t *testing.T) {
			var value wire
			require.Error(t, strictConceptDecode830G2(raw, &value))
		})
	}
	var valid wire
	require.NoError(t, strictConceptDecode830G2([]byte(`{"value":"\ud83d\ude00"}`), &valid))
	require.Equal(t, "😀", valid.Value)
	for name, payload := range map[string]any{
		"invalid string":  map[string]any{"text": string([]byte{0xff})},
		"invalid map key": map[string]any{string([]byte{0xff}): "text"},
	} {
		t.Run(name, func(t *testing.T) {
			_, err := conceptDigest830G2("canonical-vector", payload)
			require.Error(t, err)
		})
	}
}

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

func conceptHumanVector830G2(t *testing.T, mutate func(map[string]any)) []byte {
	t.Helper()
	decoder := json.NewDecoder(bytes.NewReader(conceptVector830G2(t)))
	decoder.UseNumber()
	var value map[string]any
	require.NoError(t, decoder.Decode(&value))
	value["contract"] = "concept-candidate-bundle.830.g2.v2"
	review := object830G2(t, object830G2(t, value, "review_result"), "output")
	scores := object830G2(t, review, "page_scores")
	conceptID := "concept_c730e23edec4bc4fa3035b05ad32ddffb0a0e38a841fff3c58a0eef88cdcc4b3"
	scores[conceptID] = map[string]any{
		"business_value": json.Number("15"), "reuse": json.Number("10"),
		"evidence_quality": json.Number("15"), "definability": json.Number("10"),
		"novel_identity": json.Number("8"), "name_stability": json.Number("8"),
	}
	value["admission"] = map[string]any{
		"contract": "concept-admission.830.g2.v1", "status": "NEEDS_HUMAN",
		"pending_page_ids": []any{conceptID},
	}
	if mutate != nil {
		mutate(value)
	}
	reviewRaw, err := json.Marshal(review)
	require.NoError(t, err)
	reviewExecution := object830G2(t, object830G2(t, value, "review_result"), "execution")
	reviewExecution["raw_output"] = string(reviewRaw)
	rawSum := sha256.Sum256(reviewRaw)
	reviewExecution["raw_output_hash"] = hex.EncodeToString(rawSum[:])
	delete(value, "candidate_hash")
	candidateHash, err := conceptDigest830G2("candidate-bundle", value)
	require.NoError(t, err)
	value["candidate_hash"] = candidateHash
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

func TestParseConceptCandidateBundle830G2AcceptsWholeBatchHumanAdmission(t *testing.T) {
	bundle, err := ParseConceptCandidateBundle830G2(conceptHumanVector830G2(t, nil))
	require.NoError(t, err)
	require.Equal(t, "concept-candidate-bundle.830.g2.v2", bundle.Contract)
	require.Equal(t, "NEEDS_HUMAN", bundle.Admission.Status)
	require.Equal(t, []string{"concept_c730e23edec4bc4fa3035b05ad32ddffb0a0e38a841fff3c58a0eef88cdcc4b3"}, bundle.Admission.PendingPageIDs)
}

func TestParseConceptCandidateBundle830G2AcceptsHumanAdmissionWithNoPendingPages(t *testing.T) {
	conceptID := "concept_c730e23edec4bc4fa3035b05ad32ddffb0a0e38a841fff3c58a0eef88cdcc4b3"
	raw := conceptHumanVector830G2(t, func(value map[string]any) {
		score := object830G2(t, object830G2(t, object830G2(t, value, "review_result"), "output"), "page_scores")[conceptID].(map[string]any)
		score["business_value"] = json.Number("25")
		score["reuse"] = json.Number("20")
		score["evidence_quality"] = json.Number("20")
		score["definability"] = json.Number("15")
		score["novel_identity"] = json.Number("10")
		score["name_stability"] = json.Number("10")
		object830G2(t, value, "admission")["pending_page_ids"] = []any{}
	})
	bundle, err := ParseConceptCandidateBundle830G2(raw)
	require.NoError(t, err)
	require.NotNil(t, bundle.Admission.PendingPageIDs)
	require.Empty(t, bundle.Admission.PendingPageIDs)
}

func TestParseConceptCandidateBundle830G2ProjectsFrozenHumanVector(t *testing.T) {
	raw, err := os.ReadFile("../../harness/tests/fixtures/concept_free_wiki_830_g2_human_contract_vector.json")
	require.NoError(t, err)
	bundle, err := ParseConceptCandidateBundle830G2(raw)
	require.NoError(t, err)
	require.Equal(t, "445eb52d26e123d3c80ebee08dcb2c3a36e5290a2ce9189159204a086b907c3e", bundle.CandidateHash)
	require.Equal(t, "PASS", bundle.ReviewResult.Output.Decision)
	require.Equal(t, "57b5b37fd80044a18ac67ce86c20dad93eeb4e6ada95fb351cd41ad14ede129f", bundle.ReviewResult.Execution.RawOutputHash)
	require.Equal(t, "NEEDS_HUMAN", bundle.Admission.Status)
	require.Equal(t, []string{
		"concept_c730e23edec4bc4fa3035b05ad32ddffb0a0e38a841fff3c58a0eef88cdcc4b3",
		"free_12a02ea3d724ad27839226067cfc8ae5389788df04db58fdf4e5d2b4bd38ef7d",
	}, bundle.Admission.PendingPageIDs)
	for _, pageID := range bundle.Admission.PendingPageIDs {
		require.Equal(t, 66, conceptScoreTotal830G2(bundle.ReviewResult.Output.PageScores[pageID]))
	}
}

func TestParseConceptCandidateBundle830G2RejectsInvalidHumanAdmission(t *testing.T) {
	conceptID := "concept_c730e23edec4bc4fa3035b05ad32ddffb0a0e38a841fff3c58a0eef88cdcc4b3"
	freeID := "free_12a02ea3d724ad27839226067cfc8ae5389788df04db58fdf4e5d2b4bd38ef7d"
	tests := map[string]func(map[string]any){
		"missing admission": func(value map[string]any) { delete(value, "admission") },
		"null pending": func(value map[string]any) {
			object830G2(t, value, "admission")["pending_page_ids"] = nil
		},
		"score below sixty": func(value map[string]any) {
			score := object830G2(t, object830G2(t, object830G2(t, value, "review_result"), "output"), "page_scores")[conceptID].(map[string]any)
			score["business_value"] = json.Number("8")
		},
		"review rejected": func(value map[string]any) {
			object830G2(t, object830G2(t, value, "review_result"), "output")["decision"] = "REJECT"
		},
		"pending order drift": func(value map[string]any) {
			scores := object830G2(t, object830G2(t, object830G2(t, value, "review_result"), "output"), "page_scores")
			scores[freeID] = map[string]any{
				"business_value": json.Number("15"), "reuse": json.Number("10"),
				"evidence_quality": json.Number("15"), "definability": json.Number("10"),
				"novel_identity": json.Number("10"), "name_stability": json.Number("10"),
			}
			object830G2(t, value, "admission")["pending_page_ids"] = []any{freeID, conceptID}
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			_, err := ParseConceptCandidateBundle830G2(conceptHumanVector830G2(t, mutate))
			require.ErrorIs(t, err, ErrConceptCandidateBundle830G2)
		})
	}
}

func TestParseConceptCandidateBundle830G2KeepsV1AdmissionClosed(t *testing.T) {
	raw := conceptHumanVector830G2(t, func(value map[string]any) {
		value["contract"] = "concept-candidate-bundle.830.g2.v1"
		score := object830G2(t, object830G2(t, object830G2(t, value, "review_result"), "output"), "page_scores")["concept_c730e23edec4bc4fa3035b05ad32ddffb0a0e38a841fff3c58a0eef88cdcc4b3"].(map[string]any)
		score["business_value"] = json.Number("25")
		score["reuse"] = json.Number("20")
		score["evidence_quality"] = json.Number("20")
		score["definability"] = json.Number("15")
		score["novel_identity"] = json.Number("10")
		score["name_stability"] = json.Number("10")
	})
	_, err := ParseConceptCandidateBundle830G2(raw)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G2)

	var value map[string]any
	require.NoError(t, json.Unmarshal(conceptVector830G2(t), &value))
	value["admission"] = nil
	raw, err = json.Marshal(value)
	require.NoError(t, err)
	_, err = ParseConceptCandidateBundle830G2(raw)
	require.ErrorIs(t, err, ErrConceptCandidateBundle830G2)
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
