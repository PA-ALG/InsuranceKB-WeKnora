package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/json"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func systemTestPolicy(scope types.WikiReleaseScope, principal string) *SystemAutomationPolicy {
	p := &SystemAutomationPolicy{PolicyID: "test-auto", Version: "1", Mode: SystemPolicyIsolatedMode, Enabled: true, PrincipalID: principal, APIKeyID: 9, WikiReleaseScope: scope, Capabilities: []string{"activate", "create-draft", "review"}, NotBefore: 900, ExpiresAt: 3000, SignerKeyID: "system-1"}
	p.Digest, _ = SystemAutomationPolicyDigest(p)
	return p
}

func systemTestDecision(p *SystemAutomationPolicy) *SystemPolicyDecisionReceiptV1 {
	return &SystemPolicyDecisionReceiptV1{Version: "1", Decision: "approve", Mode: p.Mode, PrincipalID: p.PrincipalID, APIKeyID: p.APIKeyID, WikiReleaseScope: p.WikiReleaseScope, PolicyID: p.PolicyID, PolicyVersion: p.Version, PolicyDigest: p.Digest, Capabilities: append([]string(nil), p.Capabilities...), PreparationID: "draft-1", DraftPreparationDigest: strings.Repeat("a", 64), CandidateDigest: strings.Repeat("b", 64), ManifestDigest: strings.Repeat("c", 64), ReadyReceiptDigest: strings.Repeat("d", 64), InnerReviewPolicyID: strings.Repeat("e", 64), ExpectedReleaseID: "parent", ExpectedActivationEpoch: 5, IssuedAt: 1000, ExpiresAt: 2000, Nonce: "system-nonce", SignerKeyID: p.SignerKeyID}
}

func signSystemTestDecision(t *testing.T, d *SystemPolicyDecisionReceiptV1, key ed25519.PrivateKey) []byte {
	t.Helper()
	preimage, err := SystemPolicyDecisionSigningBytesV1(d)
	require.NoError(t, err)
	d.Signature = EncodeWikiReleaseSignature(ed25519.Sign(key, preimage))
	raw, err := CanonicalSystemPolicyDecisionReceiptV1(d, true)
	require.NoError(t, err)
	return raw
}

func TestSystemPolicyDecisionCanonicalSignatureAndClosedWire(t *testing.T) {
	key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x38}, ed25519.SeedSize))
	p := systemTestPolicy(types.WikiReleaseScope{TenantID: 42, SpaceID: "s", RawKBID: "r", WikiKBID: "w"}, "api_tenant:42")
	d := systemTestDecision(p)
	raw := signSystemTestDecision(t, d, key)
	parsed, err := ParseSystemPolicyDecisionReceiptV1(raw)
	require.NoError(t, err)
	require.Equal(t, d, parsed)
	verifier := NewEd25519SystemPolicyDecisionVerifier(map[string]ed25519.PublicKey{"system-1": key.Public().(ed25519.PublicKey)})
	require.NoError(t, verifier.Verify(parsed))
	unsigned, err := CanonicalSystemPolicyDecisionReceiptV1(d, false)
	require.NoError(t, err)
	d.Signature = EncodeWikiReleaseSignature(ed25519.Sign(key, unsigned))
	require.Error(t, verifier.Verify(d), "bare JSON signatures must not cross the system domain")
	for _, wire := range [][]byte{append(raw, []byte(" {}")...), []byte(strings.Replace(string(raw), "{", "{\"version\":\"1\",", 1)), []byte(strings.Replace(string(raw), "{", "{\"human_batch_hash\":\"x\",", 1)), []byte(strings.Replace(string(raw), "\"decision\":\"approve\",", "", 1))} {
		_, err = ParseSystemPolicyDecisionReceiptV1(wire)
		require.Error(t, err)
	}
	raw = signSystemTestDecision(t, d, key)
	var wire map[string]any
	require.NoError(t, json.Unmarshal(raw, &wire))
	wire["expires_at"] = nil
	invalid, _ := json.Marshal(wire)
	_, err = ParseSystemPolicyDecisionReceiptV1(invalid)
	require.Error(t, err, "null cannot stand in for a required field")
	d.CandidateDigest = strings.Repeat("f", 64)
	require.Error(t, verifier.Verify(d))
	require.Error(t, NewEd25519SystemPolicyDecisionVerifier(nil).Verify(d))
}

func TestSystemPolicyCurrentExactGate(t *testing.T) {
	scope := types.WikiReleaseScope{TenantID: 42, SpaceID: "s", RawKBID: "r", WikiKBID: "w"}
	principal := types.WikiReleasePrincipal{ID: "api_tenant:42", TenantID: 42, SpaceID: "s", APIKeyKnowledgeBaseIDs: []string{"r", "w"}}
	ctx := systemTestContext(scope)
	current := systemTestPolicy(scope, principal.ID)
	s := NewWikiReleaseService(nil, nil, nil, WikiReleaseServiceOptions{SystemPolicyProvider: SystemAutomationPolicyProviderFunc(func(context.Context, types.WikiReleasePrincipal, types.WikiReleaseScope) (*SystemAutomationPolicy, error) {
		return current, nil
	})})
	s.now = func() time.Time { return time.Unix(1000, 0) }
	_, err := s.requireSystemPolicy(ctx, principal, scope, "create-draft")
	require.NoError(t, err)
	cases := map[string]func(*SystemAutomationPolicy){
		"disabled":           func(p *SystemAutomationPolicy) { p.Enabled = false },
		"production":         func(p *SystemAutomationPolicy) { p.Mode = "production" },
		"principal":          func(p *SystemAutomationPolicy) { p.PrincipalID = "api_tenant:43" },
		"scope":              func(p *SystemAutomationPolicy) { p.WikiKBID = "other" },
		"expired":            func(p *SystemAutomationPolicy) { p.ExpiresAt = 1000 },
		"future":             func(p *SystemAutomationPolicy) { p.NotBefore = 1001 },
		"missing capability": func(p *SystemAutomationPolicy) { p.Capabilities = []string{"activate", "review"} },
		"extra capability":   func(p *SystemAutomationPolicy) { p.Capabilities = append(p.Capabilities, "rollback") },
		"duplicate":          func(p *SystemAutomationPolicy) { p.Capabilities = []string{"activate", "review", "review"} },
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			current = systemTestPolicy(scope, principal.ID)
			change(current)
			current.Digest, _ = SystemAutomationPolicyDigest(current)
			_, err := s.requireSystemPolicy(ctx, principal, scope, "create-draft")
			require.Error(t, err)
		})
	}
	current = systemTestPolicy(scope, principal.ID)
	current.Digest = strings.Repeat("0", 64)
	_, err = s.requireSystemPolicy(ctx, principal, scope, "create-draft")
	require.Error(t, err)
	current = systemTestPolicy(scope, principal.ID)
	for name, alter := range map[string]func(context.Context) context.Context{
		"other key": func(c context.Context) context.Context {
			return types.WithTenantAPIKeyScope(c, types.TenantAPIKeyScope{KeyID: 10, KnowledgeBaseIDs: types.StringArray{"r", "w"}})
		},
		"shrunk key ACL": func(c context.Context) context.Context {
			return types.WithTenantAPIKeyScope(c, types.TenantAPIKeyScope{KeyID: 9, KnowledgeBaseIDs: types.StringArray{"r"}})
		},
		"human": func(c context.Context) context.Context {
			return types.WithPrincipal(c, types.Principal{Type: types.PrincipalWebUser, ID: "42"})
		},
		"platform key": func(c context.Context) context.Context {
			return types.WithTenantAPIKeyScope(c, types.TenantAPIKeyScope{KeyID: 9, ScopeType: types.APIKeyScopePlatform, KnowledgeBaseIDs: types.StringArray{"r", "w"}})
		},
	} {
		t.Run(name, func(t *testing.T) {
			_, err := s.requireSystemPolicy(alter(ctx), principal, scope, "create-draft")
			require.Error(t, err)
		})
	}
	_, err = s.requireSystemPolicy(context.Background(), principal, scope, "create-draft")
	require.Error(t, err)
	current = nil
	_, err = s.requireSystemPolicy(ctx, principal, scope, "create-draft")
	require.Error(t, err)
}

func systemTestContext(scope types.WikiReleaseScope) context.Context {
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, scope.TenantID)
	ctx = types.WithPrincipal(ctx, types.Principal{Type: types.PrincipalAPITenant, ID: strconv.FormatUint(scope.TenantID, 10)})
	return types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{KeyID: 9, KnowledgeBaseIDs: types.StringArray{scope.RawKBID, scope.WikiKBID}})
}

func TestSystemPolicyRejectsBroadMachineKey(t *testing.T) {
	scope := types.WikiReleaseScope{TenantID: 42, SpaceID: "s", RawKBID: "r", WikiKBID: "w"}
	p := types.WikiReleasePrincipal{ID: "api_tenant:42", TenantID: 42, SpaceID: "s"}
	policy := systemTestPolicy(scope, p.ID)
	s := NewWikiReleaseService(nil, nil, nil, WikiReleaseServiceOptions{Now: func() time.Time { return time.Unix(1000, 0) }, SystemPolicyProvider: SystemAutomationPolicyProviderFunc(func(context.Context, types.WikiReleasePrincipal, types.WikiReleaseScope) (*SystemAutomationPolicy, error) {
		return policy, nil
	})})
	for name, key := range map[string]types.TenantAPIKeyScope{
		"full access":  {KeyID: 9, FullAccess: true, KnowledgeBaseIDs: types.StringArray{"r", "w"}},
		"unrestricted": {KeyID: 9},
		"extra KB":     {KeyID: 9, KnowledgeBaseIDs: types.StringArray{"r", "w", "other"}},
	} {
		t.Run(name, func(t *testing.T) {
			principal := p
			principal.APIKeyKnowledgeBaseIDs = append([]string(nil), key.KnowledgeBaseIDs...)
			ctx := types.WithTenantAPIKeyScope(systemTestContext(scope), key)
			_, err := s.requireSystemPolicy(ctx, principal, scope, "create-draft")
			require.Error(t, err, "isolated policy must not authorize a broad key")
		})
	}
}
