package handler

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"testing"
	"time"
)

func platformCompositionConfig(now time.Time) *config.Config {
	pub := func(id string, n byte) config.SchemaWikiEd25519PublicKeyConfig {
		k := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{n}, 32))
		return config.SchemaWikiEd25519PublicKeyConfig{KeyID: id, PublicKeyBase64: base64.RawURLEncoding.EncodeToString(k[32:])}
	}
	return &config.Config{SchemaWikiSigning: &config.SchemaWikiSigningConfig{PublishAuthorizationPublicKeys: []config.SchemaWikiEd25519PublicKeyConfig{pub("publish", 1)}}, G3PlatformProcessing: &config.G3PlatformProcessingConfig{Enabled: true, TenantID: 1, SpaceID: "10000000-0000-0000-0000-000000000001", RawKBID: "10000000-0000-0000-0000-000000000002", WikiKBID: "10000000-0000-0000-0000-000000000003", MachinePrincipalID: "api_tenant:1", APIKeyID: 7, PolicyID: "isolated-test", PolicyVersion: "1", Mode: service.SystemPolicyIsolatedMode, NotBefore: now.Unix() - 10, ExpiresAt: now.Unix() + 300, Capabilities: []string{"activate", "create-draft", "review"}, SystemDecisionKeyID: "system", SystemDecisionPublicKeys: []config.SchemaWikiEd25519PublicKeyConfig{pub("system", 2)}, SourceSnapshotSigningKey: config.SchemaWikiEd25519PrivateKeyConfig{KeyID: "snapshot", PrivateKeyBase64: base64.RawURLEncoding.EncodeToString(ed25519.NewKeyFromSeed(bytes.Repeat([]byte{3}, 32)))}}}
}
func TestG3PlatformCompositionCurrentSystemPolicyAndIndependentVerifier(t *testing.T) {
	now := time.Unix(200, 0)
	cfg := platformCompositionConfig(now)
	opts, err := ConfiguredG3PlatformSystemOptions(cfg, func() time.Time { return now })
	require.NoError(t, err)
	require.NotNil(t, opts.SystemPolicyProvider)
	require.NotNil(t, opts.SystemDecisionVerifier)
	require.Nil(t, opts.HumanDecisionVerifier)
	scope := types.WikiReleaseScope{TenantID: 1, SpaceID: cfg.G3PlatformProcessing.SpaceID, RawKBID: cfg.G3PlatformProcessing.RawKBID, WikiKBID: cfg.G3PlatformProcessing.WikiKBID}
	p := types.WikiReleasePrincipal{ID: "api_tenant:1", TenantID: 1, SpaceID: scope.SpaceID}
	policy, err := opts.SystemPolicyProvider.CurrentPolicy(context.Background(), p, scope)
	require.NoError(t, err)
	require.Equal(t, uint64(7), policy.APIKeyID)
	require.Equal(t, service.SystemPolicyIsolatedMode, policy.Mode)
	digest, err := service.SystemAutomationPolicyDigest(policy)
	require.NoError(t, err)
	require.Equal(t, digest, policy.Digest)
	d := &service.SystemPolicyDecisionReceiptV1{Version: "system-policy-decision.v1", SignerKeyID: "system"}
	preimage, err := service.SystemPolicyDecisionSigningBytesV1(d)
	require.NoError(t, err)
	d.Signature = base64.RawURLEncoding.EncodeToString(ed25519.Sign(ed25519.NewKeyFromSeed(bytes.Repeat([]byte{2}, 32)), preimage))
	require.NoError(t, opts.SystemDecisionVerifier.Verify(d))
	d.SignerKeyID = "publish"
	require.Error(t, opts.SystemDecisionVerifier.Verify(d))
	bad := scope
	bad.TenantID = 2
	_, err = opts.SystemPolicyProvider.CurrentPolicy(context.Background(), p, bad)
	require.Error(t, err)
	policy.Capabilities[0] = "forged"
	again, err := opts.SystemPolicyProvider.CurrentPolicy(context.Background(), p, scope)
	require.NoError(t, err)
	require.Equal(t, "activate", again.Capabilities[0])
	oldKey := cfg.G3PlatformProcessing.SystemDecisionPublicKeys[0].PublicKeyBase64
	replacement := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{9}, 32))
	cfg.G3PlatformProcessing.SystemDecisionPublicKeys[0].PublicKeyBase64 = base64.RawURLEncoding.EncodeToString(replacement[32:])
	_, err = opts.SystemPolicyProvider.CurrentPolicy(context.Background(), p, scope)
	require.Error(t, err)
	cfg.G3PlatformProcessing.SystemDecisionPublicKeys[0].PublicKeyBase64 = oldKey
	cfg.G3PlatformProcessing.Enabled = false
	_, err = opts.SystemPolicyProvider.CurrentPolicy(context.Background(), p, scope)
	require.Error(t, err)
	cfg.G3PlatformProcessing.Enabled = true
	now = time.Unix(501, 0)
	_, err = opts.SystemPolicyProvider.CurrentPolicy(context.Background(), p, scope)
	require.Error(t, err)
}

type compositionKnowledgeStub struct{}

func (compositionKnowledgeStub) GetKnowledgeByID(context.Context, uint64, string) (*types.Knowledge, error) {
	return nil, nil
}
func (compositionKnowledgeStub) FindByMetadataKey(context.Context, uint64, string, string, string) (*types.Knowledge, error) {
	return nil, nil
}
func TestG3PlatformCompositionDisabledAndEnabledDependencies(t *testing.T) {
	a, b, err := NewConfiguredG3PlatformHandlers(nil, nil, nil, nil, nil, nil, nil, nil)
	require.NoError(t, err)
	require.Nil(t, a)
	require.Nil(t, b)
	cfg := platformCompositionConfig(time.Now())
	a, b, err = NewConfiguredG3PlatformHandlers(cfg, compositionKnowledgeStub{}, &service.KnowledgeRevisionSourceService{}, &service.ConceptSourceAuthorityService830G2{}, repository.NewKnowledgeSpanRepository(nil), &WikiReleaseHandler{}, &service.SchemaWikiService{}, &service.WikiReleaseService{})
	require.NoError(t, err)
	require.NotNil(t, a)
	require.NotNil(t, b)
	require.IsType(t, &service.G3PlatformMachineAccessService{}, a.uploads)
	require.IsType(t, &service.G3PlatformSourceSnapshotService{}, a.sources)
	require.IsType(t, &service.G3PlatformBaseSnapshotService{}, a.bases)
	_, _, err = NewConfiguredG3PlatformHandlers(cfg, nil, nil, nil, nil, nil, nil, nil)
	require.Error(t, err)
	opts, err := ConfiguredG3PlatformSystemOptions(nil, time.Now)
	require.NoError(t, err)
	require.Nil(t, opts.SystemPolicyProvider)
	require.Nil(t, opts.SystemDecisionVerifier)
}
