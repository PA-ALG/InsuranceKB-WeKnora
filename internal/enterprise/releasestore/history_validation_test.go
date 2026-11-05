package releasestore

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestHistoricalProjectionUsesExactJSONValueTypes(t *testing.T) {
	require.False(t, equalJSON([]byte(`{"n":1}`), []byte(`{"n":"1"}`)))
	require.False(t, equalJSON([]byte(`{"n":9007199254740993}`), []byte(`{"n":9007199254740992}`)))
	require.True(t, equalJSON([]byte(`{"n":1.00e3}`), []byte(`{"n":1000}`)))
	require.True(t, equalJSON([]byte(`{"b":[null,true,"x"],"a":-0}`), []byte(`{"a":0,"b":[null,true,"x"]}`)))
	require.False(t, equalJSON([]byte(`{} {}`), []byte(`{}`)))
}
