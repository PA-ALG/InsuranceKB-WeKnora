package container

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"os"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func schemaWikiContainerPublicKey(seed byte, keyID string) (ed25519.PrivateKey, config.SchemaWikiEd25519PublicKeyConfig) {
	privateKey := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{seed}, ed25519.SeedSize))
	return privateKey, config.SchemaWikiEd25519PublicKeyConfig{
		KeyID: keyID,
		PublicKeyBase64: base64.RawURLEncoding.EncodeToString(
			privateKey.Public().(ed25519.PublicKey),
		),
	}
}

func TestSchemaWikiProductionVerifierProvidersUseConfiguredExistingProtocols(t *testing.T) {
	t.Parallel()
	humanPrivate, humanPublic := schemaWikiContainerPublicKey(0x51, "human-key")
	publishPrivate, publishPublic := schemaWikiContainerPublicKey(0x52, "publish-key")
	_, evaluatorPublic := schemaWikiContainerPublicKey(0x53, "golden-evaluator-key")
	cfg := &config.Config{SchemaWikiSigning: &config.SchemaWikiSigningConfig{
		HumanDecisionPublicKeys:        []config.SchemaWikiEd25519PublicKeyConfig{humanPublic},
		PublishAuthorizationPublicKeys: []config.SchemaWikiEd25519PublicKeyConfig{publishPublic},
		GoldenQualityEvaluatorPublicKeys: []config.SchemaWikiEd25519PublicKeyConfig{
			evaluatorPublic,
		},
	}}
	authorizationVerifier, options, err := schemaWikiReleaseVerifierProviders(cfg)
	require.NoError(t, err)
	require.NotNil(t, authorizationVerifier)
	require.NotNil(t, options.HumanDecisionVerifier)
	require.NotNil(t, options.QualityGateReceiptVerifier)

	scope := types.WikiReleaseScope{
		TenantID: 10003, SpaceID: "space-596-1",
		RawKBID: "raw-596-1", WikiKBID: "wiki-596-1",
	}
	human := &types.HumanBatchDecisionReceiptV1{
		Version: "1", Decision: "approve", PrincipalID: "reviewer", WikiReleaseScope: scope,
		CandidateHash: strings.Repeat("a", 64), HumanBatchHash: strings.Repeat("b", 64),
		ReviewPolicyHash: strings.Repeat("c", 64), IssuedAt: 1, ExpiresAt: 2,
		Nonce: "human-nonce", SignerKeyID: "human-key",
	}
	unsignedHuman, err := service.CanonicalHumanBatchDecisionReceiptV1(human, false)
	require.NoError(t, err)
	human.Signature = service.EncodeWikiReleaseSignature(ed25519.Sign(humanPrivate, unsignedHuman))
	require.NoError(t, options.HumanDecisionVerifier.Verify(human))

	publish := &types.PublishAuthorizationV0{
		Version: "0", Action: "activate", PreparationID: "preparation-1",
		CandidateDigest: strings.Repeat("a", 64), ManifestDigest: strings.Repeat("d", 64),
		ReadyReceiptDigest: strings.Repeat("b", 64), ReviewDecisionDigest: strings.Repeat("e", 64),
		ReviewPolicyID: strings.Repeat("c", 64), TenantID: scope.TenantID,
		SpaceID: scope.SpaceID, RawKBID: scope.RawKBID, WikiKBID: scope.WikiKBID,
		ExpectedReleaseID: "", ExpectedActivationEpoch: 0, ExpiresAt: 2,
		Nonce: "human-nonce", SignerKeyID: "publish-key",
	}
	unsignedPublish, err := service.CanonicalPublishAuthorizationV0(publish, false)
	require.NoError(t, err)
	publish.Signature = service.EncodeWikiReleaseSignature(ed25519.Sign(publishPrivate, unsignedPublish))
	require.NoError(t, authorizationVerifier.Verify(publish))
}

func TestSchemaWikiProductionVerifierProvidersDefaultEmptyRejectsBothAuthorities(t *testing.T) {
	t.Parallel()
	authorizationVerifier, options, err := schemaWikiReleaseVerifierProviders(&config.Config{})
	require.NoError(t, err)
	require.Error(t, options.HumanDecisionVerifier.Verify(&types.HumanBatchDecisionReceiptV1{
		SignerKeyID: "unknown",
	}))
	require.Error(t, authorizationVerifier.Verify(&types.PublishAuthorizationV0{
		SignerKeyID: "unknown",
	}))
	require.Error(t, options.QualityGateReceiptVerifier.Verify(
		&types.Schema67GoldenQualityGateReceiptV1{SignerKeyID: "unknown"},
	))
}

func TestSchemaWikiContainerDoesNotInjectNilCitationPort(t *testing.T) {
	t.Parallel()
	raw, err := os.ReadFile("container.go")
	require.NoError(t, err)
	source := string(raw)
	require.NotContains(t, source, "NewSchemaWikiService(releaseAuthority, nil)")
	require.Contains(t, source, "NewSchemaWikiCitationRevisionReadAdapter")
	require.Contains(t, source, "DecodeSchemaWikiCitationTokenSigningRing")
	require.Contains(t, source, "NewSchemaWikiCitationContentService")
	require.Contains(t, source, "NewSchemaWikiRevisionBlobReader")
}
