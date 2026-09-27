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

func qualityFixture(t *testing.T, total int, updates bool) BatchConceptCandidateBundle830G3 {
	t.Helper()
	request, output, _ := knowledgeUpdateFixture830G3(t, "page")
	if !updates {
		request.KnowledgeUpdatePolicy = ""
	}
	raw, err := json.Marshal(request)
	require.NoError(t, err)
	var wire map[string]interface{}
	require.NoError(t, json.Unmarshal(raw, &wire))
	wire["quality_policy"] = "provenance-applicable-score.830.v1"
	raw, err = json.Marshal(wire)
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(raw, &request))
	page := output.Pages[0]
	page.Body = "模型补充说明。"
	page.Conditions = []string{}
	page.Exceptions = []string{}
	page.ValidTime = ""
	page.Evidence = []ConceptEvidence830G2{}
	page.ContentProvenance = &KnowledgeContentProvenance{Contract: "knowledge-content-provenance.830.v1", Segments: []KnowledgeContentSegment{{Text: page.Body, Origin: "MODEL_GENERATED", EvidenceIndexes: []int{}}}}
	output.Pages = []ConceptFreeWikiPage830G2{page}
	output.Definitions = nil
	output.Audit = nil
	id, err := conceptFreePageID830G2(page)
	require.NoError(t, err)
	// All values remain within their original individual maxima.
	score := ConceptValueScore830G2{BusinessValue: 25, Reuse: 20, Definability: 15, NovelIdentity: 4, NameStability: total - 64}
	return BatchConceptCandidateBundle830G3{Request: request, CompileResult: ConceptCompileResult830G2{Output: output}, ReviewResult: ConceptReviewResult830G2{Output: ConceptReviewOutput830G2{Decision: "PASS", PageScores: map[string]ConceptValueScore830G2{id: score}}}, Admission: ConceptAdmission830G2{PendingPageIDs: []string{}}}
}

func TestProvenanceQualityGeneratedAdmission(t *testing.T) {
	for _, total := range []int{64, 71} {
		bundle := qualityFixture(t, total, true)
		require.NoError(t, validateKnowledgeUpdateAdmission830G3(bundle))
	}
}
func TestProvenanceQualityIndependentlyRechecksAdmission(t *testing.T) {
	bundle := qualityFixture(t, 71, false)
	bundle.ReviewResult.Output.PageScores["unexpected"] = ConceptValueScore830G2{}
	require.Error(t, validateKnowledgeUpdateAdmission830G3(bundle))
}
func TestProvenanceQualityPreservedInRequestWire(t *testing.T) {
	bundle := qualityFixture(t, 71, false)
	raw, err := json.Marshal(bundle.Request)
	require.NoError(t, err)
	require.Contains(t, string(raw), `"quality_policy":"provenance-applicable-score.830.v1"`)
}

func TestProvenanceQualitySharedVectors(t *testing.T) {
	raw, err := os.ReadFile("../../harness/tests/fixtures/batch_concept_compile_830_g3/quality-policy-vectors.json")
	require.NoError(t, err)
	var rows []struct {
		Name       string
		Policy     string
		Content    string
		Evidence   []ConceptEvidence830G2
		Provenance *KnowledgeContentProvenance
		Score      ConceptValueScore830G2
		Maximum    int
		Band       string
		Error      bool
	}
	require.NoError(t, json.Unmarshal(raw, &rows))
	for _, row := range rows {
		t.Run(row.Name, func(t *testing.T) {
			result, err := qualifyKnowledge830(row.Policy, knowledgeQualityContent830{row.Content, row.Evidence, row.Provenance}, row.Score)
			if row.Error {
				require.Error(t, err)
				return
			}
			require.NoError(t, err)
			require.Equal(t, row.Maximum, result.ApplicableMax)
			require.Equal(t, row.Band, result.Band)
			require.Equal(t, conceptScoreTotal830G2(row.Score), result.RawTotal)
		})
	}
}
func TestProvenanceQualityCrossLanguageCandidate(t *testing.T) {
	raw, err := os.ReadFile("../../harness/tests/fixtures/batch_concept_compile_830_g3/quality-policy-candidate.json.gz")
	require.NoError(t, err)
	reader, err := gzip.NewReader(bytes.NewReader(raw))
	require.NoError(t, err)
	decoded, err := io.ReadAll(reader)
	require.NoError(t, err)
	require.NoError(t, reader.Close())
	bundle, canonical, err := CanonicalBatchConceptCandidateBundle830G3(decoded)
	require.NoError(t, err)
	require.Equal(t, decoded, canonical)
	require.Empty(t, bundle.Request.KnowledgeUpdatePolicy)
	require.Equal(t, provenanceQualityPolicy830, bundle.Request.QualityPolicy)
	require.Empty(t, bundle.Admission.PendingPageIDs)
	for _, value := range []string{"null", `""`, `"unknown"`} {
		tampered := bytes.Replace(decoded, []byte(`"quality_policy":"provenance-applicable-score.830.v1"`), []byte(`"quality_policy":`+value), 1)
		_, _, err := CanonicalBatchConceptCandidateBundle830G3(tampered)
		require.Error(t, err)
	}
	bundle.Admission.PendingPageIDs = []string{"stale"}
	require.Error(t, validateKnowledgeUpdateAdmission830G3(bundle))
}

func TestProvenanceQualityRejectsEmptyLegacyExtension(t *testing.T) {
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	for _, value := range []any{nil, ""} {
		var wire map[string]any
		require.NoError(t, json.Unmarshal(raw, &wire))
		wire["request"].(map[string]any)["quality_policy"] = value
		altered, err := json.Marshal(wire)
		require.NoError(t, err)
		_, err = ParseBatchConceptCandidateBundle830G3(altered)
		require.Error(t, err)
	}
}
