package types

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"github.com/stretchr/testify/require"
	"io"
	"os"
	"testing"
)

func relationVector(t *testing.T) (ConceptSourceBlock830G2, ConceptDefinition830G2, ConceptFreeWikiPage830G2, string) {
	t.Helper()
	raw, err := os.ReadFile("testdata/product_concept_relation_830_g3.json")
	require.NoError(t, err)
	var vector struct {
		Source     ConceptSourceBlock830G2 `json:"source"`
		Definition ConceptDefinition830G2  `json:"definition"`
		Page       json.RawMessage         `json:"page"`
		SHA        string                  `json:"page_sha256"`
	}
	require.NoError(t, json.Unmarshal(raw, &vector))
	var page ConceptFreeWikiPage830G2
	require.NoError(t, strictConceptDecode830G2(vector.Page, &page))
	return vector.Source, vector.Definition, page, vector.SHA
}

func TestProductConceptRelationPythonVector(t *testing.T) {
	source, definition, page, expected := relationVector(t)
	require.NoError(t, validateConceptMembers830G2("space", []ConceptDefinition830G2{definition}, nil, []ConceptFreeWikiPage830G2{page}))
	for _, e := range page.Evidence {
		require.NoError(t, verifyConceptEvidence830G2(e, []ConceptSourceBlock830G2{source}))
	}
	actual, err := batchConceptHash830G3("product-concept-relation-page.830.v1", page)
	require.NoError(t, err)
	require.Equal(t, expected, actual)
}

func TestProductConceptRelationRejectsTargetRevisionDrift(t *testing.T) {
	_, definition, page, _ := relationVector(t)
	definition.Body += "新义项"
	require.Error(t, validateConceptMembers830G2("space", []ConceptDefinition830G2{definition}, nil, []ConceptFreeWikiPage830G2{page}))
}

func TestProductConceptRelationRejectsInvalidShape(t *testing.T) {
	raw, err := os.ReadFile("testdata/product_concept_relation_830_g3.json")
	require.NoError(t, err)
	for _, mode := range []string{"null", "unknown", "predicate", "subject", "key", "empty-version", "missing-provenance", "model", "no-evidence"} {
		t.Run(mode, func(t *testing.T) {
			var vector map[string]any
			require.NoError(t, json.Unmarshal(raw, &vector))
			page := vector["page"].(map[string]any)
			relation := page["business_relation"].(map[string]any)
			switch mode {
			case "null":
				page["business_relation"] = nil
			case "unknown":
				relation["extra"] = true
			case "predicate":
				relation["predicate"] = "related_to"
			case "subject":
				relation["subject_type"] = "CONCEPT"
			case "key":
				page["stable_key"] = "ordinary"
			case "empty-version":
				page["entity_version"] = ""
			case "missing-provenance":
				delete(page, "content_provenance")
			case "model":
				segment := page["content_provenance"].(map[string]any)["segments"].([]any)[0].(map[string]any)
				segment["origin"] = "MODEL_GENERATED"
				segment["evidence_indexes"] = []int{}
				page["evidence"] = []any{}
			case "no-evidence":
				page["evidence"] = []any{}
			}
			wire, _ := json.Marshal(page)
			var typed ConceptFreeWikiPage830G2
			err := strictConceptDecode830G2(wire, &typed)
			if err == nil {
				err = validateConceptPage830G2(typed)
			}
			require.Error(t, err)
		})
	}
}

func TestProductConceptRelationCompleteCandidateReplay(t *testing.T) {
	raw, err := os.ReadFile("testdata/product_concept_relation_candidate.json.gz")
	require.NoError(t, err)
	reader, err := gzip.NewReader(bytes.NewReader(raw))
	require.NoError(t, err)
	wire, err := io.ReadAll(reader)
	require.NoError(t, err)
	require.NoError(t, reader.Close())
	bundle, canonical, err := CanonicalBatchConceptCandidateBundle830G3(wire)
	require.NoError(t, err)
	require.Equal(t, wire, canonical)
	count := 0
	for _, page := range bundle.CompileResult.Output.Pages {
		if page.BusinessRelation != nil {
			count++
		}
	}
	require.Equal(t, 1, count)
	require.Error(t, validateConceptOutput830G2(bundle.Request.BaseRequest, bundle.CompileResult.Output))
}
