package config

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"sort"
	"testing"

	"github.com/stretchr/testify/require"
)

func sortedSchemaWikiKeyIDs(keys map[string]ed25519.PublicKey) []string {
	ids := make([]string, 0, len(keys))
	for keyID := range keys {
		ids = append(ids, keyID)
	}
	sort.Strings(ids)
	return ids
}

func schemaWikiPublicKeyConfig(seed byte, keyID string) SchemaWikiEd25519PublicKeyConfig {
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{seed}, ed25519.SeedSize))
	return SchemaWikiEd25519PublicKeyConfig{
		KeyID:           keyID,
		PublicKeyBase64: base64.RawURLEncoding.EncodeToString(privateKey.Public().(ed25519.PublicKey)),
	}
}

func TestDecodeSchemaWikiSigningPublicKeysKeepsDecisionDomainsSeparate(t *testing.T) {
	t.Parallel()
	human := schemaWikiPublicKeyConfig(0x31, "human-key-1")
	publish := schemaWikiPublicKeyConfig(0x32, "publish-key-1")
	cfg := &Config{SchemaWikiSigning: &SchemaWikiSigningConfig{
		HumanDecisionPublicKeys:        []SchemaWikiEd25519PublicKeyConfig{human},
		PublishAuthorizationPublicKeys: []SchemaWikiEd25519PublicKeyConfig{publish},
	}}

	humanKeys, publishKeys, err := DecodeSchemaWikiSigningPublicKeys(cfg)
	require.NoError(t, err)
	require.Equal(t, []string{"human-key-1"}, sortedSchemaWikiKeyIDs(humanKeys))
	require.Equal(t, []string{"publish-key-1"}, sortedSchemaWikiKeyIDs(publishKeys))
	require.NotEqual(t, humanKeys["human-key-1"], publishKeys["publish-key-1"])
}

func TestDecodeSchemaWikiGoldenQualityEvaluatorPublicKeysRejectsDuplicateMaterial(t *testing.T) {
	t.Parallel()
	evaluator := schemaWikiPublicKeyConfig(0x33, "golden-evaluator-key-1")
	second := schemaWikiPublicKeyConfig(0x34, "golden-evaluator-key-2")
	cfg := &Config{SchemaWikiSigning: &SchemaWikiSigningConfig{
		GoldenQualityEvaluatorPublicKeys: []SchemaWikiEd25519PublicKeyConfig{
			evaluator, second,
		},
	}}

	keys, err := DecodeSchemaWikiGoldenQualityEvaluatorPublicKeys(cfg)
	require.NoError(t, err)
	require.Equal(t, []string{"golden-evaluator-key-1", "golden-evaluator-key-2"}, sortedSchemaWikiKeyIDs(keys))

	duplicateMaterial := evaluator
	duplicateMaterial.KeyID = "golden-evaluator-key-2"
	_, err = DecodeSchemaWikiGoldenQualityEvaluatorPublicKeys(&Config{
		SchemaWikiSigning: &SchemaWikiSigningConfig{
			GoldenQualityEvaluatorPublicKeys: []SchemaWikiEd25519PublicKeyConfig{
				evaluator, duplicateMaterial,
			},
		},
	})
	require.Error(t, err)
}

func TestDecodeSchemaWikiSigningPublicKeysDefaultEmptyIsSecurelyEmpty(t *testing.T) {
	t.Parallel()
	humanKeys, publishKeys, err := DecodeSchemaWikiSigningPublicKeys(&Config{})
	require.NoError(t, err)
	require.Empty(t, humanKeys)
	require.Empty(t, publishKeys)
}

func TestDecodeSchemaWikiSigningPublicKeysRejectsDuplicateAndMalformedConfig(t *testing.T) {
	t.Parallel()
	valid := schemaWikiPublicKeyConfig(0x41, "key-1")
	tests := map[string]*SchemaWikiSigningConfig{
		"duplicate human key id": {
			HumanDecisionPublicKeys: []SchemaWikiEd25519PublicKeyConfig{valid, valid},
		},
		"duplicate publish key id": {
			PublishAuthorizationPublicKeys: []SchemaWikiEd25519PublicKeyConfig{valid, valid},
		},
		"empty key id": {
			HumanDecisionPublicKeys: []SchemaWikiEd25519PublicKeyConfig{{
				KeyID: "", PublicKeyBase64: valid.PublicKeyBase64,
			}},
		},
		"key id whitespace": {
			HumanDecisionPublicKeys: []SchemaWikiEd25519PublicKeyConfig{{
				KeyID: " key-1", PublicKeyBase64: valid.PublicKeyBase64,
			}},
		},
		"bad base64": {
			HumanDecisionPublicKeys: []SchemaWikiEd25519PublicKeyConfig{{
				KeyID: "key-1", PublicKeyBase64: "not-base64",
			}},
		},
		"private key bytes": {
			HumanDecisionPublicKeys: []SchemaWikiEd25519PublicKeyConfig{{
				KeyID: "key-1",
				PublicKeyBase64: base64.RawURLEncoding.EncodeToString(
					ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x42}, ed25519.SeedSize)),
				),
			}},
		},
		"padded encoding": {
			HumanDecisionPublicKeys: []SchemaWikiEd25519PublicKeyConfig{{
				KeyID: "key-1",
				PublicKeyBase64: base64.URLEncoding.EncodeToString(
					bytes.Repeat([]byte{0x43}, ed25519.PublicKeySize),
				),
			}},
		},
	}
	for name, signing := range tests {
		name, signing := name, signing
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			_, _, err := DecodeSchemaWikiSigningPublicKeys(&Config{SchemaWikiSigning: signing})
			require.Error(t, err)
			require.Error(t, ValidateConfig(&Config{SchemaWikiSigning: signing}))
		})
	}
}

func TestDecodeSchemaWikiSigningPublicKeysRejectsCrossDomainKeyReuse(t *testing.T) {
	t.Parallel()
	human := schemaWikiPublicKeyConfig(0x51, "shared-id")
	publishDifferentMaterial := schemaWikiPublicKeyConfig(0x52, "shared-id")
	publishSameMaterial := human
	publishSameMaterial.KeyID = "publish-key"
	tests := map[string]*SchemaWikiSigningConfig{
		"duplicate key id across decision domains": {
			HumanDecisionPublicKeys:        []SchemaWikiEd25519PublicKeyConfig{human},
			PublishAuthorizationPublicKeys: []SchemaWikiEd25519PublicKeyConfig{publishDifferentMaterial},
		},
		"duplicate key material across decision domains": {
			HumanDecisionPublicKeys:        []SchemaWikiEd25519PublicKeyConfig{human},
			PublishAuthorizationPublicKeys: []SchemaWikiEd25519PublicKeyConfig{publishSameMaterial},
		},
	}
	for name, signing := range tests {
		name, signing := name, signing
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			_, _, err := DecodeSchemaWikiSigningPublicKeys(&Config{SchemaWikiSigning: signing})
			require.Error(t, err)
			require.Error(t, ValidateConfig(&Config{SchemaWikiSigning: signing}))
		})
	}
}

func TestSchemaWikiSigningPublicKeysAreExcludedFromConfigJSON(t *testing.T) {
	t.Parallel()
	publicKey := schemaWikiPublicKeyConfig(0x61, "human-key")
	raw, err := json.Marshal(&Config{SchemaWikiSigning: &SchemaWikiSigningConfig{
		HumanDecisionPublicKeys: []SchemaWikiEd25519PublicKeyConfig{publicKey},
	}})
	require.NoError(t, err)
	require.NotContains(t, string(raw), "schema_wiki_signing")
	require.NotContains(t, string(raw), "public_key_base64")
	require.NotContains(t, string(raw), publicKey.PublicKeyBase64)
}
