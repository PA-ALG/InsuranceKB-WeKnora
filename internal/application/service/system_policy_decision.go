package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"github.com/Tencent/WeKnora/internal/types"
	"slices"
	"strconv"
)

const SystemPolicyIsolatedMode = "ISOLATED_NOT_FOR_PRODUCTION"

// SystemAutomationPolicy is current server authority, never caller-supplied policy.
type SystemAutomationPolicy struct {
	PolicyID    string `json:"policy_id"`
	Version     string `json:"version"`
	Digest      string `json:"digest"`
	Mode        string `json:"mode"`
	Enabled     bool   `json:"enabled"`
	PrincipalID string `json:"principal_id"`
	APIKeyID    uint64 `json:"api_key_id"`
	types.WikiReleaseScope
	Capabilities []string `json:"capabilities"`
	NotBefore    int64    `json:"not_before"`
	ExpiresAt    int64    `json:"expires_at"`
	SignerKeyID  string   `json:"signer_key_id"`
}

type SystemAutomationPolicyProvider interface {
	CurrentPolicy(context.Context, types.WikiReleasePrincipal, types.WikiReleaseScope) (*SystemAutomationPolicy, error)
}
type SystemAutomationPolicyProviderFunc func(context.Context, types.WikiReleasePrincipal, types.WikiReleaseScope) (*SystemAutomationPolicy, error)

func (f SystemAutomationPolicyProviderFunc) CurrentPolicy(c context.Context, p types.WikiReleasePrincipal, s types.WikiReleaseScope) (*SystemAutomationPolicy, error) {
	return f(c, p, s)
}

type SystemPolicyDecisionReceiptV1 struct {
	Version     string `json:"version"`
	Decision    string `json:"decision"`
	Mode        string `json:"mode"`
	PrincipalID string `json:"principal_id"`
	APIKeyID    uint64 `json:"api_key_id"`
	types.WikiReleaseScope
	PolicyID                string   `json:"policy_id"`
	PolicyVersion           string   `json:"policy_version"`
	PolicyDigest            string   `json:"policy_digest"`
	Capabilities            []string `json:"capabilities"`
	PreparationID           string   `json:"preparation_id"`
	DraftPreparationDigest  string   `json:"draft_preparation_digest"`
	CandidateDigest         string   `json:"candidate_digest"`
	ManifestDigest          string   `json:"manifest_digest"`
	ReadyReceiptDigest      string   `json:"ready_receipt_digest"`
	InnerReviewPolicyID     string   `json:"inner_review_policy_id"`
	ExpectedReleaseID       string   `json:"expected_release_id"`
	ExpectedActivationEpoch uint64   `json:"expected_activation_epoch"`
	IssuedAt                int64    `json:"issued_at"`
	ExpiresAt               int64    `json:"expires_at"`
	Nonce                   string   `json:"nonce"`
	SignerKeyID             string   `json:"signer_key_id"`
	Signature               string   `json:"signature"`
}
type SystemPolicyDecisionVerifier interface {
	Verify(*SystemPolicyDecisionReceiptV1) error
}
type ed25519SystemPolicyDecisionVerifier struct{ keys map[string]ed25519.PublicKey }

// System decision signatures cannot be substituted for a human receipt or a
// PublishAuthorizationV0, even when a deployment accidentally reuses a key.
const systemPolicyDecisionDomainV1 = "system-policy-decision.v1\x00"

func NewEd25519SystemPolicyDecisionVerifier(keys map[string]ed25519.PublicKey) SystemPolicyDecisionVerifier {
	frozen := make(map[string]ed25519.PublicKey, len(keys))
	for id, key := range keys {
		frozen[id] = append(ed25519.PublicKey(nil), key...)
	}
	return &ed25519SystemPolicyDecisionVerifier{keys: frozen}
}
func (v *ed25519SystemPolicyDecisionVerifier) Verify(d *SystemPolicyDecisionReceiptV1) error {
	if v == nil || d == nil {
		return ErrWikiReleaseInvalidAuthorization
	}
	key := v.keys[d.SignerKeyID]
	signature, err := base64.RawURLEncoding.DecodeString(d.Signature)
	if err != nil || len(key) != ed25519.PublicKeySize || len(signature) != ed25519.SignatureSize {
		return ErrWikiReleaseInvalidAuthorization
	}
	preimage, err := SystemPolicyDecisionSigningBytesV1(d)
	if err != nil || !ed25519.Verify(key, preimage, signature) {
		return ErrWikiReleaseInvalidAuthorization
	}
	return nil
}

// SystemAutomationPolicyDigest binds the complete current policy, including
// enablement, key, scope, capabilities and lifetime; Digest itself is excluded.
func SystemAutomationPolicyDigest(p *SystemAutomationPolicy) (string, error) {
	if p == nil {
		return "", ErrWikiReleaseInvalidAuthorization
	}
	raw, err := canonicalSystemObject(p, "digest")
	if err != nil {
		return "", err
	}
	return digestWikiReleaseBytes(append([]byte("system-automation-policy.v1\x00"), raw...)), nil
}

var systemPolicyDecisionFields = func() map[string]struct{} {
	raw, _ := json.Marshal(SystemPolicyDecisionReceiptV1{})
	var object map[string]json.RawMessage
	_ = json.Unmarshal(raw, &object)
	fields := make(map[string]struct{}, len(object))
	for name := range object {
		fields[name] = struct{}{}
	}
	return fields
}()

func ParseSystemPolicyDecisionReceiptV1(raw []byte) (*SystemPolicyDecisionReceiptV1, error) {
	fields, err := parseClosedJSONObject(raw, systemPolicyDecisionFields)
	if err != nil {
		return nil, err
	}
	for name := range systemPolicyDecisionFields {
		value, ok := fields[name]
		if !ok || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return nil, ErrWikiReleaseInvalidAuthorization
		}
	}
	var d SystemPolicyDecisionReceiptV1
	if err := json.Unmarshal(raw, &d); err != nil {
		return nil, ErrWikiReleaseInvalidAuthorization
	}
	return &d, nil
}

func canonicalSystemObject(value any, exclude string) ([]byte, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return nil, ErrWikiReleaseInvalidAuthorization
	}
	var fields map[string]json.RawMessage
	if err = json.Unmarshal(raw, &fields); err != nil {
		return nil, ErrWikiReleaseInvalidAuthorization
	}
	if exclude != "" {
		delete(fields, exclude)
	}
	return json.Marshal(fields)
}
func CanonicalSystemPolicyDecisionReceiptV1(d *SystemPolicyDecisionReceiptV1, signed bool) ([]byte, error) {
	if d == nil {
		return nil, ErrWikiReleaseInvalidAuthorization
	}
	exclude := ""
	if !signed {
		exclude = "signature"
	}
	return canonicalSystemObject(d, exclude)
}
func SystemPolicyDecisionSigningBytesV1(d *SystemPolicyDecisionReceiptV1) ([]byte, error) {
	raw, err := CanonicalSystemPolicyDecisionReceiptV1(d, false)
	if err != nil {
		return nil, err
	}
	return append([]byte(systemPolicyDecisionDomainV1), raw...), nil
}

func exactSystemCapabilities(capabilities []string) bool {
	return slices.Equal(capabilities, []string{"activate", "create-draft", "review"})
}

func (s *WikiReleaseService) requireSystemPolicy(ctx context.Context, p types.WikiReleasePrincipal, scope types.WikiReleaseScope, capability string) (*SystemAutomationPolicy, error) {
	if s == nil || s.systemPolicyProvider == nil || ctx == nil {
		return nil, ErrWikiReleaseAccessDenied
	}
	terminal, ok := types.PrincipalFromContext(ctx)
	key, keyOK := types.TenantAPIKeyScopeFromContext(ctx)
	tenant, tenantOK := types.TenantIDFromContext(ctx)
	declared := append([]string(nil), p.APIKeyKnowledgeBaseIDs...)
	actual := append([]string(nil), key.KnowledgeBaseIDs...)
	slices.Sort(declared)
	slices.Sort(actual)
	if !ok || terminal.Type != types.PrincipalAPITenant || terminal.ID != strconv.FormatUint(scope.TenantID, 10) ||
		terminal.StorageID() != p.ID || !keyOK || key.KeyID == 0 || key.FullAccess || key.IsPlatform() || !tenantOK || tenant != scope.TenantID ||
		p.TenantID != scope.TenantID || p.SpaceID != scope.SpaceID || scope.TenantID == 0 || scope.SpaceID == "" || scope.RawKBID == "" || scope.WikiKBID == "" ||
		scope.RawKBID == scope.WikiKBID || len(actual) != 2 || !key.AllowsKnowledgeBase(scope.RawKBID) || !key.AllowsKnowledgeBase(scope.WikiKBID) || !slices.Equal(declared, actual) {
		return nil, ErrWikiReleaseAccessDenied
	}
	current, err := s.systemPolicyProvider.CurrentPolicy(ctx, p, scope)
	if err != nil || current == nil {
		return nil, ErrWikiReleaseAccessDenied
	}
	policy := *current
	policy.Capabilities = append([]string(nil), current.Capabilities...)
	digest, err := SystemAutomationPolicyDigest(&policy)
	now := s.now().Unix()
	if err != nil || !policy.Enabled || policy.Mode != SystemPolicyIsolatedMode || policy.PrincipalID != p.ID || policy.APIKeyID != key.KeyID ||
		policy.WikiReleaseScope != scope || !validBatchConceptPreparationID830G3(policy.PolicyID) || !validBatchConceptPreparationID830G3(policy.Version) ||
		!validBatchConceptPreparationID830G3(policy.SignerKeyID) || !isLowerHexSHA256(policy.Digest) || policy.Digest != digest ||
		policy.NotBefore <= 0 || policy.NotBefore > now || policy.ExpiresAt <= now || !exactSystemCapabilities(policy.Capabilities) ||
		!slices.Contains(policy.Capabilities, capability) {
		return nil, ErrWikiReleaseAccessDenied
	}
	return &policy, nil
}

func (s *WikiReleaseService) verifySystemDecision(raw []byte, policy *SystemAutomationPolicy, allowExpired bool) (*SystemPolicyDecisionReceiptV1, string, error) {
	d, err := ParseSystemPolicyDecisionReceiptV1(raw)
	if err != nil {
		return nil, "", err
	}
	canonical, err := CanonicalSystemPolicyDecisionReceiptV1(d, true)
	if err != nil || !bytes.Equal(raw, canonical) || s.systemDecisionVerifier == nil {
		return nil, "", ErrWikiReleaseInvalidAuthorization
	}
	if err := s.systemDecisionVerifier.Verify(d); err != nil {
		return nil, "", err
	}
	now := s.now().Unix()
	if d.Version != "1" || d.Decision != "approve" || d.Mode != SystemPolicyIsolatedMode ||
		d.PrincipalID != policy.PrincipalID || d.APIKeyID != policy.APIKeyID || d.WikiReleaseScope != policy.WikiReleaseScope ||
		d.PolicyID != policy.PolicyID || d.PolicyVersion != policy.Version || d.PolicyDigest != policy.Digest || d.SignerKeyID != policy.SignerKeyID ||
		!exactSystemCapabilities(d.Capabilities) || !validBatchConceptPreparationID830G3(d.PreparationID) ||
		!validBatchConceptPreparationID830G3(d.Nonce) || !validBatchConceptPreparationID830G3(d.ExpectedReleaseID) ||
		d.IssuedAt < policy.NotBefore || d.IssuedAt > now || d.ExpiresAt <= d.IssuedAt || d.ExpiresAt > policy.ExpiresAt || (!allowExpired && d.ExpiresAt <= now) {
		return nil, "", fmt.Errorf("%w: system decision identity or lifetime mismatch", ErrWikiReleaseInvalidAuthorization)
	}
	for _, digest := range []string{d.DraftPreparationDigest, d.CandidateDigest, d.ManifestDigest, d.ReadyReceiptDigest, d.InnerReviewPolicyID} {
		if !isLowerHexSHA256(digest) {
			return nil, "", ErrWikiReleaseInvalidAuthorization
		}
	}
	return d, digestWikiReleaseBytes(canonical), nil
}
