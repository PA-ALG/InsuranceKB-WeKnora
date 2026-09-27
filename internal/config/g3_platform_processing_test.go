package config

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"github.com/stretchr/testify/require"
	"testing"
	"time"
)

func g3ProcessingFixture() *Config {
	public := func(id string, seed byte) SchemaWikiEd25519PublicKeyConfig {
		k := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{seed}, 32))
		return SchemaWikiEd25519PublicKeyConfig{KeyID: id, PublicKeyBase64: base64.RawURLEncoding.EncodeToString(k[32:])}
	}
	return &Config{SchemaWikiSigning: &SchemaWikiSigningConfig{PublishAuthorizationPublicKeys: []SchemaWikiEd25519PublicKeyConfig{public("publish", 1)}}, G3PlatformProcessing: &G3PlatformProcessingConfig{
		Enabled: true, TenantID: 1, SpaceID: "10000000-0000-0000-0000-000000000001", RawKBID: "10000000-0000-0000-0000-000000000002", WikiKBID: "10000000-0000-0000-0000-000000000003",
		MachinePrincipalID: "api_tenant:1", APIKeyID: 7, PolicyID: "isolated-test", PolicyVersion: "1", Mode: "ISOLATED_NOT_FOR_PRODUCTION", NotBefore: 100, ExpiresAt: 300, Capabilities: []string{"activate", "create-draft", "review"}, SystemDecisionKeyID: "system", SystemDecisionPublicKeys: []SchemaWikiEd25519PublicKeyConfig{public("system", 2)}, SourceSnapshotSigningKey: SchemaWikiEd25519PrivateKeyConfig{KeyID: "snapshot", PrivateKeyBase64: base64.RawURLEncoding.EncodeToString(ed25519.NewKeyFromSeed(bytes.Repeat([]byte{3}, 32)))}}}
}
func TestG3PlatformProcessingConfigExplicitAndPrivate(t *testing.T) {
	now := time.Unix(200, 0)
	for _, cfg := range []*Config{nil, {}, {G3PlatformProcessing: &G3PlatformProcessingConfig{}}} {
		got, err := DecodeG3PlatformProcessing(cfg, now)
		require.NoError(t, err)
		require.Nil(t, got)
	}
	cfg := g3ProcessingFixture()
	got, err := DecodeG3PlatformProcessing(cfg, now)
	require.NoError(t, err)
	require.NotNil(t, got)
	require.Equal(t, cfg.G3PlatformProcessing.RawKBID, got.Scope.RawKBID)
	require.Len(t, got.SnapshotSigningKey(), 64)
	require.Len(t, got.SystemDecisionKeys(), 1)
	key := got.SnapshotSigningKey()
	key[0] ^= 1
	require.NotEqual(t, key, got.SnapshotSigningKey())
	keys := got.SystemDecisionKeys()
	keys["system"][0] ^= 1
	require.NotEqual(t, keys, got.SystemDecisionKeys())
	raw, err := json.Marshal(cfg)
	require.NoError(t, err)
	require.NotContains(t, string(raw), "g3_platform_processing")
	require.NotContains(t, string(raw), cfg.G3PlatformProcessing.SourceSnapshotSigningKey.PrivateKeyBase64)
	cfg.G3PlatformProcessing.Capabilities[0] = "forged"
	require.Equal(t, "activate", got.Settings.Capabilities[0])
}
func TestG3PlatformProcessingConfigRejectsIncompleteOrSharedAuthority(t *testing.T) {
	cases := map[string]func(*Config){
		"missing":         func(c *Config) { c.G3PlatformProcessing = &G3PlatformProcessingConfig{Enabled: true} },
		"wrong-principal": func(c *Config) { c.G3PlatformProcessing.MachinePrincipalID = "api_tenant:2" },
		"no-key":          func(c *Config) { c.G3PlatformProcessing.APIKeyID = 0 },
		"production":      func(c *Config) { c.G3PlatformProcessing.Mode = "production" },
		"expired":         func(c *Config) { c.G3PlatformProcessing.ExpiresAt = 200 },
		"future":          func(c *Config) { c.G3PlatformProcessing.NotBefore = 201 },
		"no-version":      func(c *Config) { c.G3PlatformProcessing.PolicyVersion = "" },
		"scope":           func(c *Config) { c.G3PlatformProcessing.RawKBID = c.G3PlatformProcessing.WikiKBID },
		"caps":            func(c *Config) { c.G3PlatformProcessing.Capabilities = []string{"review"} },
		"unknown-key":     func(c *Config) { c.G3PlatformProcessing.SystemDecisionKeyID = "unknown" },
		"no-publish":      func(c *Config) { c.SchemaWikiSigning = nil },
		"same-id": func(c *Config) {
			c.G3PlatformProcessing.SystemDecisionPublicKeys[0].KeyID = "publish"
			c.G3PlatformProcessing.SystemDecisionKeyID = "publish"
		},
		"same-public": func(c *Config) {
			c.G3PlatformProcessing.SystemDecisionPublicKeys[0].PublicKeyBase64 = c.SchemaWikiSigning.PublishAuthorizationPublicKeys[0].PublicKeyBase64
		},
		"same-snapshot": func(c *Config) {
			c.G3PlatformProcessing.SourceSnapshotSigningKey.PrivateKeyBase64 = base64.RawURLEncoding.EncodeToString(ed25519.NewKeyFromSeed(bytes.Repeat([]byte{2}, 32)))
		},
		"corrupt-private": func(c *Config) {
			k := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{3}, 32))
			k[63] ^= 1
			c.G3PlatformProcessing.SourceSnapshotSigningKey.PrivateKeyBase64 = base64.RawURLEncoding.EncodeToString(k)
		},
		"frozen-scope-drift": func(c *Config) {
			c.SchemaWikiFrozenReleaseScope = &SchemaWikiFrozenReleaseScopeConfig{Enabled: true, TenantID: 2, SpaceID: c.G3PlatformProcessing.SpaceID, RawKBID: c.G3PlatformProcessing.RawKBID, WikiKBID: c.G3PlatformProcessing.WikiKBID}
		},
	}
	cases["browser-scope-drift"] = func(c *Config) {
		c.ProductIngestion = &ProductIngestionConfig{Enabled: true, TenantID: 2, SpaceID: c.G3PlatformProcessing.SpaceID, RawKBID: c.G3PlatformProcessing.RawKBID, WikiKBID: c.G3PlatformProcessing.WikiKBID}
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			c := g3ProcessingFixture()
			change(c)
			got, err := DecodeG3PlatformProcessing(c, time.Unix(200, 0))
			require.Error(t, err)
			require.Nil(t, got)
			require.EqualError(t, err, "G3 platform processing configuration invalid")
		})
	}
}
