package types

import (
	"compress/gzip"
	"encoding/json"
	"io"
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

func knowledgeUpdateFixture830G3(t *testing.T, kind string) (BatchConceptCompileRequest830G3, ConceptCompileOutput830G2, string) {
	t.Helper()
	raw, err := os.ReadFile(batchConceptFixture830G3)
	require.NoError(t, err)
	var bundle BatchConceptCandidateBundle830G3
	require.NoError(t, json.Unmarshal(raw, &bundle))
	bundle.Request.KnowledgeUpdatePolicy = "explicit-same-identity.830.v1"
	bundle.Request.RequestSHA256, err = batchConceptHashWithout830G3(
		bundle.Request.Contract, bundle.Request, "request_sha256")
	require.NoError(t, err)
	delta := bundle.ModelCompileResult.Output
	var id string
	if kind == "page" {
		page := bundle.Request.BaseRequest.ExistingPages[0]
		page.Body += " 更新说明。"
		delta.Pages = []ConceptFreeWikiPage830G2{page}
		id, err = conceptFreePageID830G2(page)
	} else {
		definition := bundle.Request.BaseRequest.ExistingDefinitions[0]
		definition.Body += " 更新说明。"
		delta.Definitions = []ConceptDefinition830G2{definition}
		id, err = conceptDefinitionID830G2(definition)
	}
	require.NoError(t, err)
	delta.Audit = append(delta.Audit, ConceptAuditDisposition830G2{Key: id, Disposition: "update", Reason: "SYNTHETIC_UPDATE_TEST"})
	return bundle.Request, delta, id
}

func TestKnowledgeUpdate830G3ReplacesMemberAndPreservesBase(t *testing.T) {
	for _, kind := range []string{"page", "definition"} {
		t.Run(kind, func(t *testing.T) {
			request, delta, id := knowledgeUpdateFixture830G3(t, kind)
			before, err := json.Marshal(request)
			require.NoError(t, err)
			require.NoError(t, validateDelta830G3(request, delta))
			output, err := composeBatchOutput830G3(request, delta)
			require.NoError(t, err)
			if kind == "page" {
				require.Equal(t, delta.Pages, output.Pages)
				require.Equal(t, request.BaseRequest.ExistingDefinitions, output.Definitions)
			} else {
				require.Equal(t, delta.Definitions, output.Definitions)
				require.Equal(t, request.BaseRequest.ExistingPages, output.Pages)
			}
			found := 0
			for _, item := range output.Audit {
				if item.Key == id {
					found++
					require.Equal(t, "update", item.Disposition)
				}
			}
			require.Equal(t, 1, found)
			after, err := json.Marshal(request)
			require.NoError(t, err)
			require.Equal(t, before, after)
		})
	}
}

func TestKnowledgeUpdate830G3RejectsUndeclaredAndNoop(t *testing.T) {
	for _, kind := range []string{"page", "definition"} {
		for _, mode := range []string{"undeclared", "unchanged"} {
			t.Run(kind+"/"+mode, func(t *testing.T) {
				request, delta, _ := knowledgeUpdateFixture830G3(t, kind)
				if mode == "undeclared" {
					delta.Audit[len(delta.Audit)-1].Disposition = "new_page"
				} else if kind == "page" {
					delta.Pages = request.BaseRequest.ExistingPages
				} else {
					delta.Definitions = request.BaseRequest.ExistingDefinitions
				}
				require.Error(t, validateDelta830G3(request, delta))
			})
		}
	}
}

func TestKnowledgeUpdate830G3RequiresExplicitPolicy(t *testing.T) {
	request, delta, _ := knowledgeUpdateFixture830G3(t, "page")
	require.NoError(t, validateBatchRequest830G3(request))
	request.KnowledgeUpdatePolicy = ""
	require.Error(t, validateDelta830G3(request, delta))
	request.KnowledgeUpdatePolicy = "unknown-policy"
	require.Error(t, validateBatchRequest830G3(request))
}

func updateCandidateVector830G3(t *testing.T) BatchConceptCandidateBundle830G3 {
	t.Helper()
	file, err := os.Open("../../harness/tests/fixtures/batch_concept_compile_830_g3/knowledge-updates-candidate.json.gz")
	require.NoError(t, err)
	defer file.Close()
	reader, err := gzip.NewReader(file)
	require.NoError(t, err)
	defer reader.Close()
	raw, err := io.ReadAll(reader)
	require.NoError(t, err)
	bundle, canonical, err := CanonicalBatchConceptCandidateBundle830G3(raw)
	require.NoError(t, err)
	require.Equal(t, raw, canonical)
	require.Equal(t, "5bc149f5becb1d7ba618df6b674cd13ae7911ef1d104816604b7c283233f1d24", bundle.CandidateHash)
	return bundle
}

func TestKnowledgeUpdate830G3PythonCandidateAndAdmissionFence(t *testing.T) {
	for _, mode := range []string{"missing", "low", "pending", "stale-review"} {
		t.Run(mode, func(t *testing.T) {
			bundle := updateCandidateVector830G3(t)
			id, err := conceptFreePageID830G2(bundle.ModelCompileResult.Output.Pages[0])
			require.NoError(t, err)
			if mode == "missing" {
				bundle.ReviewResult.Output.PageScores = map[string]ConceptValueScore830G2{}
			} else if mode == "stale-review" {
				bundle.ReviewResult.Output.OutputHash = bundle.Request.RequestSHA256
			} else {
				score := bundle.ReviewResult.Output.PageScores[id]
				score.BusinessValue = 0
				if mode == "low" {
					score.Reuse = 0
				}
				bundle.ReviewResult.Output.PageScores[id] = score
			}
			raw, err := batchConceptCanonicalJSON830G3(bundle.ReviewResult.Output)
			require.NoError(t, err)
			bundle.ReviewResult.Execution.RawOutput = string(raw)
			bundle.ReviewResult.Execution.RawOutputHash = sha256Hex830G3(raw)
			bundle.CandidateHash, err = batchConceptHashWithout830G3(bundle.Contract, bundle, "candidate_hash")
			require.NoError(t, err)
			raw, err = batchConceptCanonicalJSON830G3(bundle)
			require.NoError(t, err)
			_, err = ParseBatchConceptCandidateBundle830G3(raw)
			require.Error(t, err)
		})
	}
}
