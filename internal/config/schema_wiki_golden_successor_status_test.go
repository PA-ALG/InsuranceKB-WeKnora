package config

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestDecodeSchemaWikiGoldenSuccessorStatusIsDeploymentOwnedAndFailClosed(t *testing.T) {
	t.Parallel()
	raw, err := os.ReadFile("../types/testdata/schema_wiki_golden_successor_status_596_1.json")
	require.NoError(t, err)
	digest := sha256.Sum256(raw)
	configured := &Config{SchemaWikiGoldenSuccessorStatus: &SchemaWikiGoldenSuccessorStatusConfig{
		CanonicalJSON: string(raw), CanonicalSHA256: hex.EncodeToString(digest[:]),
	}}
	decoded, err := DecodeSchemaWikiGoldenSuccessorStatus(configured)
	require.NoError(t, err)
	require.Equal(t, raw, decoded)
	decoded[0] = 'x'
	require.NotEqual(t, decoded, raw)
	require.NoError(t, ValidateConfig(configured))

	missing, err := DecodeSchemaWikiGoldenSuccessorStatus(&Config{})
	require.NoError(t, err)
	require.Nil(t, missing)

	for name, cfg := range map[string]*SchemaWikiGoldenSuccessorStatusConfig{
		"missing digest": {CanonicalJSON: string(raw)},
		"digest drift":   {CanonicalJSON: string(raw), CanonicalSHA256: strings.Repeat("f", 64)},
		"trailing json": {
			CanonicalJSON: string(raw) + `{}`,
			CanonicalSHA256: func() string {
				sum := sha256.Sum256(append(append([]byte(nil), raw...), []byte(`{}`)...))
				return hex.EncodeToString(sum[:])
			}(),
		},
	} {
		t.Run(name, func(t *testing.T) {
			candidate := &Config{SchemaWikiGoldenSuccessorStatus: cfg}
			_, err := DecodeSchemaWikiGoldenSuccessorStatus(candidate)
			require.Error(t, err)
			require.Error(t, ValidateConfig(candidate))
		})
	}

	marshaled, err := json.Marshal(configured)
	require.NoError(t, err)
	require.NotContains(t, string(marshaled), "schema_wiki_golden_successor_status")
	require.NotContains(t, string(marshaled), configured.SchemaWikiGoldenSuccessorStatus.CanonicalSHA256)
}
