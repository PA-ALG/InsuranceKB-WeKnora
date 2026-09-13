package types

import (
	"context"
	"errors"
	"testing"
)

type modelDispatchRecorderTestStub struct {
	spec ModelDispatchSpec
	err  error
}

func (s *modelDispatchRecorderTestStub) ReserveModelDispatch(
	_ context.Context, spec ModelDispatchSpec,
) (ModelDispatchReservation, error) {
	s.spec = spec
	return nil, s.err
}

func TestModelDispatchRecorderContextIsExplicitAndOptional(t *testing.T) {
	spec := ModelDispatchSpec{
		Operation: "embedding", Purpose: "document_embedding",
		ModelID: "model-1", ModelName: "qwen", RequestSHA256: string(make([]byte, 64)),
	}
	if reservation, err := ReserveModelDispatch(context.Background(), spec); err != nil || reservation != nil {
		t.Fatalf("missing recorder = (%v, %v), want (nil, nil)", reservation, err)
	}

	wantErr := errors.New("journal unavailable")
	recorder := &modelDispatchRecorderTestStub{err: wantErr}
	ctx := WithModelDispatchRecorder(context.Background(), recorder)
	if _, err := ReserveModelDispatch(ctx, spec); !errors.Is(err, wantErr) {
		t.Fatalf("ReserveModelDispatch error = %v, want %v", err, wantErr)
	}
	if recorder.spec != spec {
		t.Fatalf("recorder spec = %#v, want %#v", recorder.spec, spec)
	}
}
