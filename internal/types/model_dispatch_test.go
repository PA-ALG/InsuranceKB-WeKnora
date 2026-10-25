package types

import (
	"context"
	"testing"
)

func TestModelAutomaticRetryPolicyIsExplicit(t *testing.T) {
	base := context.Background()
	for _, ctx := range []context.Context{nil, base} {
		if ModelAutomaticRetryDisabled(ctx) {
			t.Fatal("absent policy must not disable legacy retries")
		}
	}
	disabled := WithModelAutomaticRetryDisabled(base)
	child, cancel := context.WithCancel(disabled)
	defer cancel()
	if !ModelAutomaticRetryDisabled(child) || ModelAutomaticRetryDisabled(base) {
		t.Fatal("explicit policy must propagate to child contexts without changing the parent")
	}
	if WithModelAutomaticRetryDisabled(nil) != nil {
		t.Fatal("nil context should remain nil")
	}
}
