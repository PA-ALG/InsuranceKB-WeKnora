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

func TestKnowledgeContentProvenanceAcceptsExplicitGeneratedSupplement(t *testing.T) {
	pageRaw := []byte(`{"space_id":"space","entity_id":"entity","stable_key":"guide","title":"阅读提示","body":"模型补充","evidence":[],"concept_ids":[],"conditions":[],"exceptions":[],"entity_version":"v1","valid_time":"","content_provenance":{"contract":"knowledge-content-provenance.830.v1","segments":[{"text":"模型补充","origin":"MODEL_GENERATED","evidence_indexes":[]}]}}`)
	var page ConceptFreeWikiPage830G2
	require.NoError(t, strictConceptDecode830G2(pageRaw, &page))
	require.NoError(t, validateConceptPage830G2(page))
	definitionRaw := []byte(`{"space_id":"space","canonical_key":"guide","sense_key":"general","title":"阅读提示","body":"模型补充","evidence":[],"aliases":[],"origin":"MODEL_COMPILE","content_provenance":{"contract":"knowledge-content-provenance.830.v1","segments":[{"text":"模型补充","origin":"MODEL_GENERATED","evidence_indexes":[]}]}}`)
	var definition ConceptDefinition830G2
	require.NoError(t, strictConceptDecode830G2(definitionRaw, &definition))
	require.NoError(t, validateConceptDefinition830G2(definition))
}

func TestKnowledgeContentProvenanceRequiresSynthesize(t *testing.T) {
	page := ConceptFreeWikiPage830G2{SpaceID: "space", EntityID: "entity", StableKey: "guide", Title: "阅读提示", Body: "补充", Evidence: []ConceptEvidence830G2{}, EntityVersion: "v1", ContentProvenance: &KnowledgeContentProvenance{Contract: "knowledge-content-provenance.830.v1", Segments: []KnowledgeContentSegment{{Text: "补充", Origin: "MODEL_GENERATED", EvidenceIndexes: []int{}}}}}
	request := ConceptCompileRequest830G2{SpaceID: "space", RequiredFields: map[string][]string{"entity": {}}, EntityVersions: map[string]string{"entity": "v1"}}
	output := ConceptCompileOutput830G2{Contract: "concept-compile-output.830.g2.v1", Pages: []ConceptFreeWikiPage830G2{page}, Transformation: "SYNTHESIZE"}
	require.NoError(t, validateConceptOutputShapeCoverage830G2(request, output))
	for _, transformation := range []string{"EXTRACT", "NORMALIZE", "COMPRESS"} {
		output.Transformation = transformation
		require.Error(t, validateConceptOutputShapeCoverage830G2(request, output), transformation)
	}
}

func TestKnowledgeContentProvenanceCrossLanguageCandidate(t *testing.T) {
	raw, err := os.ReadFile("../../harness/tests/fixtures/batch_concept_compile_830_g3/content-provenance-candidate.json.gz")
	require.NoError(t, err)
	reader, err := gzip.NewReader(bytes.NewReader(raw))
	require.NoError(t, err)
	decoded, err := io.ReadAll(reader)
	require.NoError(t, err)
	require.NoError(t, reader.Close())
	bundle, canonical, err := CanonicalBatchConceptCandidateBundle830G3(decoded)
	require.NoError(t, err)
	require.Equal(t, decoded, canonical)
	require.Equal(t, "SYNTHESIZE", bundle.CompileResult.Output.Transformation)
	require.Empty(t, bundle.ModelCompileResult.Output.Pages[0].Evidence)
	require.Contains(t, string(canonical), "MODEL_GENERATED")
}

func TestKnowledgeContentProvenanceRejectsMalformedWire(t *testing.T) {
	base := map[string]any{"space_id": "space", "entity_id": "entity", "stable_key": "guide", "title": "说明", "body": "补充", "evidence": []any{}, "concept_ids": []any{}, "conditions": []any{}, "exceptions": []any{}, "entity_version": "v1", "valid_time": "", "content_provenance": map[string]any{"contract": "knowledge-content-provenance.830.v1", "segments": []any{map[string]any{"text": "补充", "origin": "MODEL_GENERATED", "evidence_indexes": []any{}}}}}
	for _, mode := range []string{"null", "missing-evidence", "null-evidence", "missing-indexes", "null-indexes", "unknown-origin", "empty-segments", "extra-field", "coverage"} {
		t.Run(mode, func(t *testing.T) {
			raw, err := json.Marshal(base)
			require.NoError(t, err)
			var changed map[string]any
			require.NoError(t, json.Unmarshal(raw, &changed))
			provenance := changed["content_provenance"].(map[string]any)
			segment := provenance["segments"].([]any)[0].(map[string]any)
			switch mode {
			case "null":
				changed["content_provenance"] = nil
			case "missing-evidence":
				delete(changed, "evidence")
			case "null-evidence":
				changed["evidence"] = nil
			case "missing-indexes":
				delete(segment, "evidence_indexes")
			case "null-indexes":
				segment["evidence_indexes"] = nil
			case "unknown-origin":
				segment["origin"] = "VERIFIED"
			case "empty-segments":
				provenance["segments"] = []any{}
			case "extra-field":
				segment["verified"] = true
			case "coverage":
				changed["body"] = "额外内容"
			}
			raw, err = json.Marshal(changed)
			require.NoError(t, err)
			var page ConceptFreeWikiPage830G2
			err = strictConceptDecode830G2(raw, &page)
			if err == nil {
				err = validateConceptPage830G2(page)
			}
			require.Error(t, err)
		})
	}
}

func TestKnowledgeContentProvenanceCarriedIntoNextBatch(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(raw, &bundle))
	base := publishedIncrementalBase830G3(t, batchConceptFixture830G3)
	page := &base.ExistingPages[0]
	page.ContentProvenance = &KnowledgeContentProvenance{Contract: "knowledge-content-provenance.830.v1", Segments: []KnowledgeContentSegment{{Text: conceptFreePageContent830G3(*page), Origin: "MODEL_GENERATED", EvidenceIndexes: []int{}}}}
	page.Evidence = []ConceptEvidence830G2{}
	bundle.Request.BaseRequest = base
	bundle.Request.UnknownFieldKeyAlignments = nil
	requestHash, err := compileRequestHash830G3(base)
	require.NoError(t, err)
	delta := ConceptCompileOutput830G2{Contract: "concept-compile-output.830.g2.v1", RequestHash: requestHash, Transformation: "EXTRACT"}
	result, err := composeBatchOutput830G3(bundle.Request, delta)
	require.NoError(t, err)
	require.Equal(t, "SYNTHESIZE", result.Transformation)
}
