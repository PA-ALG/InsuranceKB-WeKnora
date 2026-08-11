package config

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"
)

func schemaWikiCitationTokenPrivateKey(seed byte, keyID string) SchemaWikiEd25519PrivateKeyConfig {
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{seed}, ed25519.SeedSize))
	return SchemaWikiEd25519PrivateKeyConfig{
		KeyID: keyID, PrivateKeyBase64: base64.RawURLEncoding.EncodeToString(privateKey),
	}
}

func TestDecodeSchemaWikiCitationTokenSigningRingIsThirdDisjointDomain(t *testing.T) {
	t.Parallel()
	human := schemaWikiPublicKeyConfig(0x71, "human-key")
	publish := schemaWikiPublicKeyConfig(0x72, "publish-key")
	token := schemaWikiCitationTokenPrivateKey(0x73, "citation-token-key")
	cfg := &Config{SchemaWikiSigning: &SchemaWikiSigningConfig{
		HumanDecisionPublicKeys:        []SchemaWikiEd25519PublicKeyConfig{human},
		PublishAuthorizationPublicKeys: []SchemaWikiEd25519PublicKeyConfig{publish},
		CitationTokenSigningKeys:       []SchemaWikiEd25519PrivateKeyConfig{token},
		ActiveCitationTokenKeyID:       token.KeyID,
	}}
	ring, err := DecodeSchemaWikiCitationTokenSigningRing(cfg)
	require.NoError(t, err)
	require.Equal(t, token.KeyID, ring.ActiveKeyID())

	for name, signing := range map[string]*SchemaWikiSigningConfig{
		"key id reused with review": {
			HumanDecisionPublicKeys: []SchemaWikiEd25519PublicKeyConfig{human},
			CitationTokenSigningKeys: []SchemaWikiEd25519PrivateKeyConfig{
				schemaWikiCitationTokenPrivateKey(0x73, human.KeyID),
			}, ActiveCitationTokenKeyID: human.KeyID,
		},
		"derived public material reused with publish": {
			PublishAuthorizationPublicKeys: []SchemaWikiEd25519PublicKeyConfig{publish},
			CitationTokenSigningKeys: []SchemaWikiEd25519PrivateKeyConfig{
				schemaWikiCitationTokenPrivateKey(0x72, "citation-key"),
			}, ActiveCitationTokenKeyID: "citation-key",
		},
	} {
		t.Run(name, func(t *testing.T) {
			_, err := DecodeSchemaWikiCitationTokenSigningRing(&Config{SchemaWikiSigning: signing})
			require.Error(t, err)
		})
	}
}

func TestSchemaWikiCitationTokenPrivateKeysNeverMarshal(t *testing.T) {
	t.Parallel()
	key := schemaWikiCitationTokenPrivateKey(0x74, "citation-token-key")
	raw, err := json.Marshal(&Config{SchemaWikiSigning: &SchemaWikiSigningConfig{
		CitationTokenSigningKeys: []SchemaWikiEd25519PrivateKeyConfig{key},
		ActiveCitationTokenKeyID: key.KeyID,
	}})
	require.NoError(t, err)
	require.NotContains(t, string(raw), "citation_token_signing_keys")
	require.NotContains(t, string(raw), "private_key_base64")
	require.NotContains(t, string(raw), key.PrivateKeyBase64)
}
