package retriever

import (
	"context"
	"errors"
	"reflect"
	"testing"

	"github.com/Tencent/WeKnora/internal/models/embedding"
	"github.com/Tencent/WeKnora/internal/types"
)

// G3 quota: a model call marked "no automatic retry" embeds once; legacy
// callers keep upstream's backoff replay.
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

func TestBatchEmbedNoAutomaticReplayPolicy(t *testing.T) {
	quota := errors.New(`EmbedBatch API error: Http Status 429 Too Many Requests, Response: {"error":{"code":"insufficient_quota"}}`)
	for _, tc := range []struct {
		name              string
		disabled, success bool
		calls             int
	}{
		{name: "g3_quota", disabled: true, calls: 1},
		{name: "legacy_quota", calls: 5},
		{name: "g3_success", disabled: true, success: true, calls: 1},
		{name: "legacy_success", success: true, calls: 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			ctx := context.Background()
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
