package config

import (
	"github.com/stretchr/testify/require"
	"gopkg.in/yaml.v3"
	"testing"
)

func TestProductNativeCandidatePolicyRejectsUnknownAndIncompleteBindings(t *testing.T) {
	for _, body := range []string{
		`{"enabled":true,"wiki_producer_policy":"typo"}`,
		`{"enabled":true,"wiki_producer_policy":"native-candidates.830.v1"}`,
	} {
		var cfg Config
		// Use the actual config decoder shape, so old code silently ignores the new policy.
		var product ProductIngestionConfig
		require.NoError(t, yaml.Unmarshal([]byte(body), &product))
		cfg.ProductIngestion = &product
		require.Error(t, ValidateConfig(&cfg), body)
	}
}

func TestProductNativeCandidatePolicyIsExactAndOptIn(t *testing.T) {
	cfg := &Config{ProductIngestion: &ProductIngestionConfig{
		Enabled: true, TenantID: 42, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki",
		WikiProducerPolicy: NativeCandidatesPolicy,
	}}
	require.NoError(t, ValidateConfig(cfg))
	require.True(t, cfg.NativeCandidateScopeEnabled(42, "space", "raw", "wiki"))
	require.False(t, cfg.NativeCandidateScopeEnabled(42, "wrong", "raw", "wiki"))
	require.False(t, cfg.NativeCandidateScopeEnabled(42, "space", "wiki", "raw"))

	require.True(t, cfg.NativeWikiWritesDisabled(42, "raw"))
	require.True(t, cfg.NativeWikiWritesDisabled(42, "wiki"))
	require.False(t, cfg.NativeWikiWritesDisabled(43, "raw"))
	require.False(t, cfg.NativeWikiWritesDisabled(42, "unrelated"))
	cfg.ProductIngestion.WikiProducerPolicy = ""
	require.False(t, cfg.NativeWikiWritesDisabled(42, "raw"))
	require.NoError(t, ValidateConfig(cfg))
	require.False(t, (*Config)(nil).NativeWikiWritesDisabled(42, "raw"))
}
