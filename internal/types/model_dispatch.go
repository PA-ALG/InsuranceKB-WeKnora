package types

import (
	"context"
	"errors"
)

// ErrModelDispatchJournalUnavailable distinguishes durable-accounting failures
// from provider failures. Callers in a journal-enabled parse must fail closed
// instead of falling back to an unaccounted model result.
var ErrModelDispatchJournalUnavailable = errors.New("model dispatch journal unavailable")

// ModelDispatchSpec contains only safe transport identity. RequestSHA256 binds
// the exact outbound bytes without persisting model input in processing spans.
type ModelDispatchSpec struct {
	Operation           string
	Purpose             string
	ModelID             string
	ModelName           string
	RequestSHA256       string
	TransportRetryIndex int
}

// ModelDispatchResult describes the observed return from one HTTP dispatch.
// It intentionally excludes response bytes and error text.
type ModelDispatchResult struct {
	Outcome    string
	HTTPStatus int
}

// ModelDispatchReservation is the durable state machine for one network send.
type ModelDispatchReservation interface {
	MarkDispatching(context.Context) error
	RecordModelDispatch(context.Context, ModelDispatchResult) error
}

// ModelDispatchRecorder reserves a durable receipt before a provider request.
type ModelDispatchRecorder interface {
	ReserveModelDispatch(context.Context, ModelDispatchSpec) (ModelDispatchReservation, error)
}

type modelDispatchRecorderContextKey struct{}

// WithModelDispatchRecorder scopes durable accounting to an explicitly opted-in
// operation. Ordinary model calls retain their existing behavior.
func WithModelDispatchRecorder(ctx context.Context, recorder ModelDispatchRecorder) context.Context {
	if ctx == nil || recorder == nil {
		return ctx
	}
	return context.WithValue(ctx, modelDispatchRecorderContextKey{}, recorder)
}

// ReserveModelDispatch is a no-op when the caller did not opt into journaling.
func ReserveModelDispatch(ctx context.Context, spec ModelDispatchSpec) (ModelDispatchReservation, error) {
	if ctx == nil {
		return nil, nil
	}
	recorder, _ := ctx.Value(modelDispatchRecorderContextKey{}).(ModelDispatchRecorder)
	if recorder == nil {
		return nil, nil
	}
	return recorder.ReserveModelDispatch(ctx, spec)
}
