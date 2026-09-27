package types

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestCanonicalBatchConceptWirePreservesPersistedSourceText(t *testing.T) {
	// Storage escaping and object order may change, while source code points
	// and integer precision must survive without NFC or float conversion.
	want := []byte("{\"number\":9007199254740993,\"text\":\"e\u0301<&>\u2028\"}")
	got, err := CanonicalBatchConceptWire830G3([]byte(` { "text": "e\u0301\u003c\u0026\u003e\u2028", "number":9007199254740993 } `))
	require.NoError(t, err)
	require.Equal(t, want, got)
	for _, bad := range []string{`{"x":1,"x":2}`, `{"x":"\ud800"}`, `{"x":1.5}`, `{"x":1e2}`, `{} {}`} {
		_, err := CanonicalBatchConceptWire830G3([]byte(bad))
		require.Error(t, err, bad)
	}
}
