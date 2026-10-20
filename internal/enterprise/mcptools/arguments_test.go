package mcptools

import (
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestEvidenceIndexAcceptsOnlyBoundedPlainIntegers(t *testing.T) {
	for _, tc := range []struct {
		raw   string
		value int
	}{{"0", 0}, {"1", 1}, {"999999", 999999}} {
		t.Run(tc.raw, func(t *testing.T) {
			value, ok := nonnegativeInteger(json.RawMessage(tc.raw))
			require.True(t, ok)
			require.Equal(t, tc.value, value)
		})
	}
	// These are literal project-layer inputs, not JSON already decoded by the SDK.
	for _, raw := range []string{
		`"1"`, `null`, `true`, `1.5`, `-1`, `-0`, `01`, `1.0`, `1e2`,
		`1000000`, `9223372036854775808`, `1e1000000000`, `1e-1000000000`,
		`1.00000000000000000000001`,
	} {
		t.Run(raw, func(t *testing.T) {
			_, ok := nonnegativeInteger(json.RawMessage(raw))
			require.False(t, ok)
		})
	}
}
