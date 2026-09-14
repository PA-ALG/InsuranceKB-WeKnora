package retriever

import (
	"context"
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/models/embedding"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

type capturingEmbedder struct {
	embedding.Embedder
	text       string
	batchTexts []string
}

func (e *capturingEmbedder) Embed(ctx context.Context, text string) ([]float32, error) {
	e.text = text
	return []float32{1}, nil
}

func (e *capturingEmbedder) BatchEmbedWithPool(
	ctx context.Context,
	model embedding.Embedder,
	texts []string,
) ([][]float32, error) {
	e.batchTexts = append([]string(nil), texts...)
	embeddings := make([][]float32, len(texts))
	for i := range texts {
		embeddings[i] = []float32{1}
	}
	return embeddings, nil
}

type saveOnlyRepository struct {
	interfaces.RetrieveEngineRepository
}

func (r *saveOnlyRepository) Save(ctx context.Context, indexInfo *types.IndexInfo, params map[string]any) error {
	return nil
}

func (r *saveOnlyRepository) BatchSave(
	ctx context.Context,
	indexInfoList []*types.IndexInfo,
	params map[string]any,
) error {
	return nil
}

func TestIndexRemovesInlineImagePayloadBeforeEmbedding(t *testing.T) {
	ctx := context.Background()
	embedder := &capturingEmbedder{}
	service := &KeywordsVectorHybridRetrieveEngineService{indexRepository: &saveOnlyRepository{}}
	payload := strings.Repeat("A", 300)
	content := "before <img src=\"data:image/png;base64," + payload + "\"> after"

	err := service.Index(ctx, embedder, &types.IndexInfo{
		Content:  content,
		SourceID: "source-1",
	}, []types.RetrieverType{types.VectorRetrieverType})
	if err != nil {
		t.Fatalf("Index returned error: %v", err)
	}
	assertImagePayloadRemoved(t, embedder.text, payload)
}

func TestBatchIndexRemovesInlineImagePayloadBeforeEmbedding(t *testing.T) {
	ctx := context.Background()
	embedder := &capturingEmbedder{}
	service := &KeywordsVectorHybridRetrieveEngineService{indexRepository: &saveOnlyRepository{}}
	payload := strings.Repeat("A", 300)
	content := "before ![chart](data:image/png;base64," + payload + ") after"

	err := service.BatchIndex(ctx, embedder, []*types.IndexInfo{{
		Content:  content,
		SourceID: "source-1",
	}}, []types.RetrieverType{types.VectorRetrieverType})
	if err != nil {
		t.Fatalf("BatchIndex returned error: %v", err)
	}
	if len(embedder.batchTexts) != 1 {
		t.Fatalf("expected one embedding input, got %d", len(embedder.batchTexts))
	}
	assertImagePayloadRemoved(t, embedder.batchTexts[0], payload)
}

func TestBatchIndexTruncatesOversizedEmbeddingInput(t *testing.T) {
	ctx := context.Background()
	embedder := &capturingEmbedder{}
	service := &KeywordsVectorHybridRetrieveEngineService{indexRepository: &saveOnlyRepository{}}

	err := service.BatchIndex(ctx, embedder, []*types.IndexInfo{{
		Content:  strings.Repeat("x", safetyMaxChars+10),
		SourceID: "source-1",
	}}, []types.RetrieverType{types.VectorRetrieverType})
	if err != nil {
		t.Fatalf("BatchIndex returned error: %v", err)
	}
	if len(embedder.batchTexts) != 1 {
		t.Fatalf("expected one embedding input, got %d", len(embedder.batchTexts))
	}
	if got := len([]rune(embedder.batchTexts[0])); got > safetyMaxChars {
		t.Fatalf("embedding input length = %d, want <= %d", got, safetyMaxChars)
	}
}

func assertImagePayloadRemoved(t *testing.T, content string, payload string) {
	t.Helper()
	if strings.Contains(content, "data:image/png;base64") || strings.Contains(content, payload) {
		t.Fatalf("embedding input still contains inline image payload: %q", content)
	}
	if !strings.Contains(content, "before") || !strings.Contains(content, "after") {
		t.Fatalf("embedding input should preserve surrounding text, got %q", content)
	}
}

type quotaBatchEmbedder struct {
	embedding.Embedder
	calls     int
	wantTexts []string
	result    [][]float32
	err       error
}

func (e *quotaBatchEmbedder) BatchEmbedWithPool(_ context.Context, _ embedding.Embedder, texts []string) ([][]float32, error) {
	e.calls++
	e.wantTexts = append([]string{}, texts...)
	return e.result, e.err
}

type outerRetryRecorder struct{ types.ModelDispatchRecorder }

func TestBatchEmbedNoAutomaticReplayPolicy(t *testing.T) {
	quota := errors.New(`EmbedBatch API error: Http Status 429 Too Many Requests, Response: {"error":{"code":"insufficient_quota"}}`)
	for _, tc := range []struct {
		name                        string
		disabled, recorded, success bool
		calls                       int
	}{
		{name: "g3_quota", disabled: true, calls: 1},
		{name: "legacy_quota", calls: 5},
		{name: "recorder_does_not_change_policy", recorded: true, calls: 5},
		{name: "g3_success", disabled: true, success: true, calls: 1},
		{name: "legacy_success", success: true, calls: 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			ctx := context.Background()
			if tc.recorded {
				ctx = types.WithModelDispatchRecorder(ctx, &outerRetryRecorder{})
			}
			if tc.disabled {
				ctx = types.WithModelAutomaticRetryDisabled(ctx)
			}
			e := &quotaBatchEmbedder{result: [][]float32{{1, 2}}, err: quota}
			if tc.success {
				e.err = nil
			}
			texts := []string{"chunk already embedded before quota", "quota chunk"}
			got, err := batchEmbedWithBackoff(ctx, e, texts)
			if e.calls != tc.calls {
				t.Fatalf("whole-list invocations=%d, want %d", e.calls, tc.calls)
			}
			if err != e.err || !reflect.DeepEqual(got, e.result) || !reflect.DeepEqual(e.wantTexts, texts) {
				t.Fatalf("original result/input/error changed: got=%v err=%v", got, err)
			}
		})
	}
}
