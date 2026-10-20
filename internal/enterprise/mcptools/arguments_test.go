package mcptools

import (
	"encoding/json"
	"strconv"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestEvidenceIntegerConversionIsExactAndBounded(t *testing.T) {
	maxInt := int(^uint(0) >> 1)
	for _, tc := range []struct {
		raw   string
		value int
	}{
		{"100.0", 100},
		{"0.10e1", 1},
		{"100e-2", 1},
		{"100000e-4", 10},
		{"10.10e2", 1010},
		{"1e+2", 100},
		{"-0.0", 0},
		{strconv.Itoa(maxInt), maxInt},
	} {
		t.Run(tc.raw, func(t *testing.T) {
			value, ok := nonnegativeInteger(json.RawMessage(tc.raw))
			require.True(t, ok)
			require.Equal(t, tc.value, value)
		})
	}
	for _, raw := range []string{
		`"0"`, `null`, `true`, `1.1`, `100e-3`, `-0.1`, `-10`,
		`1e1000000000`, `1e-1000000000`, `1.00000000000000000000001`,
		`9223372036854775808`, `1e9223372036854775807`, `1e-9223372036854775808`,
	} {
		t.Run(raw, func(t *testing.T) {
			_, ok := nonnegativeInteger(json.RawMessage(raw))
			require.False(t, ok)
		})
	}
}
