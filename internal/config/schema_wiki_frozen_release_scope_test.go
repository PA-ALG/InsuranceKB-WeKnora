package config

import (
	"encoding/json"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestDecodeSchemaWikiFrozenReleaseScopeDefaultsDisabled(t *testing.T) {
	t.Parallel()

	scope, err := DecodeSchemaWikiFrozenReleaseScope(&Config{})
	require.NoError(t, err)
	require.Nil(t, scope)
}

func TestDecodeSchemaWikiFrozenReleaseScopeAcceptsExplicitCanonicalScope(t *testing.T) {
	t.Parallel()

	cfg := &Config{SchemaWikiFrozenReleaseScope: &SchemaWikiFrozenReleaseScopeConfig{
		Enabled:  true,
		TenantID: 42,
		SpaceID:  "11111111-1111-4111-8111-111111111111",
		RawKBID:  "22222222-2222-4222-8222-222222222222",
		WikiKBID: "33333333-3333-4333-8333-333333333333",
	}}

	scope, err := DecodeSchemaWikiFrozenReleaseScope(cfg)
	require.NoError(t, err)
	require.Equal(t, &types.WikiReleaseScope{
		TenantID: 42,
		SpaceID:  "11111111-1111-4111-8111-111111111111",
		RawKBID:  "22222222-2222-4222-8222-222222222222",
		WikiKBID: "33333333-3333-4333-8333-333333333333",
	}, scope)

	raw, err := json.Marshal(cfg)
	require.NoError(t, err)
	require.NotContains(t, string(raw), "11111111-1111-4111-8111-111111111111")
}

func TestDecodeSchemaWikiFrozenReleaseScopeRejectsPartialOrNonCanonicalConfig(t *testing.T) {
	t.Parallel()

	valid := SchemaWikiFrozenReleaseScopeConfig{
		Enabled:  true,
		TenantID: 42,
		SpaceID:  "11111111-1111-4111-8111-111111111111",
		RawKBID:  "22222222-2222-4222-8222-222222222222",
		WikiKBID: "33333333-3333-4333-8333-333333333333",
	}
	tests := map[string]SchemaWikiFrozenReleaseScopeConfig{
		"disabled_with_stale_identity": {
			TenantID: valid.TenantID,
		},
		"missing_tenant": {
			Enabled: true, SpaceID: valid.SpaceID, RawKBID: valid.RawKBID, WikiKBID: valid.WikiKBID,
		},
		"uppercase_uuid": {
			Enabled: true, TenantID: valid.TenantID,
			SpaceID: "11111111-1111-4111-8111-11111111111A",
			RawKBID: valid.RawKBID, WikiKBID: valid.WikiKBID,
		},
		"duplicate_identity": {
			Enabled: true, TenantID: valid.TenantID,
			SpaceID: valid.SpaceID, RawKBID: valid.RawKBID, WikiKBID: valid.RawKBID,
		},
	}

	for name, configured := range tests {
		configured := configured
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			_, err := DecodeSchemaWikiFrozenReleaseScope(&Config{
				SchemaWikiFrozenReleaseScope: &configured,
			})
			require.Error(t, err)
		})
	}
}
