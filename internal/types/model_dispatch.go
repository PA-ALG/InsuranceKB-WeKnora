package types

import "context"

type modelAutomaticRetryDisabledContextKey struct{}

// WithModelAutomaticRetryDisabled explicitly forbids automatic model replay in
// this operation.
func WithModelAutomaticRetryDisabled(ctx context.Context) context.Context {
	if ctx == nil {
		return nil
	}
	return context.WithValue(ctx, modelAutomaticRetryDisabledContextKey{}, true)
}

func ModelAutomaticRetryDisabled(ctx context.Context) bool {
	if ctx == nil {
		return false
	}
	disabled, _ := ctx.Value(modelAutomaticRetryDisabledContextKey{}).(bool)
	return disabled
}
