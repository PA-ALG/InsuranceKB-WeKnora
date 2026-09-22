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

func TestModelAutomaticRetryPolicyIsExplicitAndIndependentOfRecorder(t *testing.T) {
	base := context.Background()
	recorder := &modelDispatchRecorderTestStub{}
	recorded := WithModelDispatchRecorder(base, recorder)
	if ModelAutomaticRetryDisabled(nil) || ModelAutomaticRetryDisabled(base) || ModelAutomaticRetryDisabled(recorded) {
		t.Fatal("recorder presence or absent policy must not disable legacy retries")
	}
	disabled := WithModelAutomaticRetryDisabled(recorded)
	child, cancel := context.WithCancel(disabled)
	defer cancel()
	if !ModelAutomaticRetryDisabled(child) || ModelAutomaticRetryDisabled(base) {
		t.Fatal("explicit policy must propagate to child contexts without changing the parent")
	}
	if _, err := ReserveModelDispatch(disabled, ModelDispatchSpec{Operation: "embedding"}); err != nil || recorder.spec.Operation != "embedding" {
		t.Fatal("retry policy must preserve the existing recorder")
	}
	if WithModelAutomaticRetryDisabled(nil) != nil {
		t.Fatal("nil context should remain nil")
	}
}
