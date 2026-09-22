package config

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"errors"
	"github.com/Tencent/WeKnora/internal/types"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

// G3PlatformProcessingConfig is deployment authority, excluded from Config JSON.
type G3PlatformProcessingConfig struct {
	Enabled                  bool                               `yaml:"enabled"`
	TenantID                 uint64                             `yaml:"tenant_id"`
	SpaceID                  string                             `yaml:"space_id"`
	RawKBID                  string                             `yaml:"raw_kb_id"`
	WikiKBID                 string                             `yaml:"wiki_kb_id"`
	MachinePrincipalID       string                             `yaml:"machine_principal_id"`
	APIKeyID                 uint64                             `yaml:"api_key_id"`
	PolicyID                 string                             `yaml:"policy_id"`
	PolicyVersion            string                             `yaml:"policy_version"`
	Mode                     string                             `yaml:"mode"`
	NotBefore                int64                              `yaml:"not_before"`
	ExpiresAt                int64                              `yaml:"expires_at"`
	Capabilities             []string                           `yaml:"capabilities"`
	SystemDecisionKeyID      string                             `yaml:"system_decision_key_id"`
	SystemDecisionPublicKeys []SchemaWikiEd25519PublicKeyConfig `yaml:"system_decision_public_keys"`
	SourceSnapshotSigningKey SchemaWikiEd25519PrivateKeyConfig  `yaml:"source_snapshot_signing_key" json:"-"`
}

type G3PlatformProcessingRuntime struct {
	Settings    G3PlatformProcessingConfig `json:"-"`
	Scope       types.WikiReleaseScope
	systemKeys  map[string]ed25519.PublicKey
	snapshotKey ed25519.PrivateKey
}

func (r *G3PlatformProcessingRuntime) SystemDecisionKeys() map[string]ed25519.PublicKey {
	result := map[string]ed25519.PublicKey{}
	if r != nil {
		for id, key := range r.systemKeys {
			result[id] = append(ed25519.PublicKey(nil), key...)
		}
	}
	return result
}
func (r *G3PlatformProcessingRuntime) SnapshotSigningKey() ed25519.PrivateKey {
	if r == nil {
		return nil
	}
	return append(ed25519.PrivateKey(nil), r.snapshotKey...)
}

var errG3PlatformProcessingConfig = errors.New("G3 platform processing configuration invalid")

// DecodeG3PlatformProcessing validates explicit isolated deployment authority.
// It never derives a machine identity, policy, lifetime, or signing key.
func DecodeG3PlatformProcessing(cfg *Config, now time.Time) (*G3PlatformProcessingRuntime, error) {
	if cfg == nil || cfg.G3PlatformProcessing == nil || !cfg.G3PlatformProcessing.Enabled {
		return nil, nil
	}
	c := cfg.G3PlatformProcessing
	if c.MachinePrincipalID != "api_tenant:"+strconv.FormatUint(c.TenantID, 10) || c.APIKeyID == 0 ||
		!validG3PlatformConfigID(c.PolicyID) || !validG3PlatformConfigID(c.PolicyVersion) || c.Mode != "ISOLATED_NOT_FOR_PRODUCTION" ||
		c.NotBefore <= 0 || c.NotBefore > now.Unix() || c.ExpiresAt <= now.Unix() || c.ExpiresAt <= c.NotBefore ||
		!slices.Equal(c.Capabilities, []string{"activate", "create-draft", "review"}) {
		return nil, errG3PlatformProcessingConfig
	}
	scope, err := DecodeSchemaWikiFrozenReleaseScope(&Config{SchemaWikiFrozenReleaseScope: &SchemaWikiFrozenReleaseScopeConfig{
		Enabled: true, TenantID: c.TenantID, SpaceID: c.SpaceID, RawKBID: c.RawKBID, WikiKBID: c.WikiKBID,
	}})
	if err != nil {
		return nil, errG3PlatformProcessingConfig
	}
	frozen, err := DecodeSchemaWikiFrozenReleaseScope(cfg)
	if err != nil || (frozen != nil && *frozen != *scope) {
		return nil, errG3PlatformProcessingConfig
	}
	if b := cfg.ProductIngestion; b != nil && b.Enabled && (b.TenantID != scope.TenantID || b.SpaceID != scope.SpaceID || b.RawKBID != scope.RawKBID || b.WikiKBID != scope.WikiKBID) {
		return nil, errG3PlatformProcessingConfig
	}
	system, err := decodeSchemaWikiPublicKeyRing("system policy", c.SystemDecisionPublicKeys)
	if err != nil || len(system[c.SystemDecisionKeyID]) != ed25519.PublicKeySize {
		return nil, errG3PlatformProcessingConfig
	}
	entry := c.SourceSnapshotSigningKey
	raw, err := base64.RawURLEncoding.DecodeString(entry.PrivateKeyBase64)
	if err != nil || len(raw) != ed25519.PrivateKeySize || base64.RawURLEncoding.EncodeToString(raw) != entry.PrivateKeyBase64 ||
		!bytes.Equal(raw, ed25519.NewKeyFromSeed(raw[:ed25519.SeedSize])) || !validG3PlatformConfigID(entry.KeyID) {
		return nil, errG3PlatformProcessingConfig
	}
	snapshotKey := append(ed25519.PrivateKey(nil), raw...)
	human, publish, err := DecodeSchemaWikiSigningPublicKeys(cfg)
	if err != nil || len(publish) == 0 {
		return nil, errG3PlatformProcessingConfig
	}
	golden, err := DecodeSchemaWikiGoldenQualityEvaluatorPublicKeys(cfg)
	if err != nil {
		return nil, errG3PlatformProcessingConfig
	}
	citation, err := DecodeSchemaWikiCitationTokenSigningRing(cfg)
	if err != nil {
		return nil, errG3PlatformProcessingConfig
	}
	// Existing domains retain their validators. New domains must have distinct
	// key IDs and public material across every existing and new authority.
	ids := map[string]bool{}
	material := map[string]bool{}
	add := func(id string, key ed25519.PublicKey) bool {
		if ids[id] || material[string(key)] {
			return false
		}
		ids[id] = true
		material[string(key)] = true
		return true
	}
	for _, ring := range []map[string]ed25519.PublicKey{human, publish, golden} {
		for id, key := range ring {
			if !add(id, key) {
				return nil, errG3PlatformProcessingConfig
			}
		}
	}
	for id, key := range citation.SigningKeys() {
		if !add(id, key.Public().(ed25519.PublicKey)) {
			return nil, errG3PlatformProcessingConfig
		}
	}
	for id, key := range system {
		if !add(id, key) {
			return nil, errG3PlatformProcessingConfig
		}
	}
	if !add(entry.KeyID, snapshotKey.Public().(ed25519.PublicKey)) {
		return nil, errG3PlatformProcessingConfig
	}
	settings := *c
	settings.Capabilities = append([]string(nil), c.Capabilities...)
	settings.SystemDecisionPublicKeys = nil
	settings.SourceSnapshotSigningKey.PrivateKeyBase64 = ""
	return &G3PlatformProcessingRuntime{Settings: settings, Scope: *scope, systemKeys: system, snapshotKey: snapshotKey}, nil
}
func validG3PlatformConfigID(s string) bool {
	return s != "" && utf8.ValidString(s) && strings.TrimSpace(s) == s && strings.IndexFunc(s, func(r rune) bool { return r < 0x20 || r == 0x7f }) < 0
}
