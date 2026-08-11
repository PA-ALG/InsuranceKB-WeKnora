package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"slices"
	"sort"
	"strings"
	"time"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/google/uuid"
	"golang.org/x/text/unicode/norm"
)

// ErrWikiReleaseInvalidAuthorization is returned for any closed-envelope,
// canonicalization, signer, or signature failure.
var (
	ErrWikiReleaseInvalidAuthorization = errors.New("invalid wiki release authorization")
	ErrWikiReleaseAccessDenied         = errors.New("wiki release access denied")
	ErrWikiReleaseConflict             = errors.New("wiki release conflict")
	ErrWikiReleaseNotFound             = errors.New("wiki release not found")
)

var publishAuthorizationV0Fields = map[string]struct{}{
	"version":                   {},
	"action":                    {},
	"preparation_id":            {},
	"candidate_digest":          {},
	"manifest_digest":           {},
	"ready_receipt_digest":      {},
	"review_decision_digest":    {},
	"review_policy_id":          {},
	"tenant_id":                 {},
	"space_id":                  {},
	"raw_kb_id":                 {},
	"wiki_kb_id":                {},
	"expected_release_id":       {},
	"expected_activation_epoch": {},
	"expires_at":                {},
	"nonce":                     {},
	"signer_key_id":             {},
	"signature":                 {},
}

var humanBatchDecisionReceiptV1Fields = map[string]struct{}{
	"version": {}, "decision": {}, "principal_id": {}, "tenant_id": {},
	"space_id": {}, "raw_kb_id": {}, "wiki_kb_id": {},
	"candidate_hash": {}, "human_batch_hash": {}, "review_policy_hash": {},
	"issued_at": {}, "expires_at": {}, "nonce": {}, "signer_key_id": {},
	"signature": {},
}

// ParsePublishAuthorizationV0 parses the experimental S0-R authorization.
func ParsePublishAuthorizationV0(raw []byte) (*types.PublishAuthorizationV0, error) {
	fields, err := parseClosedJSONObject(raw, publishAuthorizationV0Fields)
	if err != nil {
		return nil, err
	}
	for name := range publishAuthorizationV0Fields {
		if _, ok := fields[name]; !ok {
			return nil, fmt.Errorf("%w: missing field %q", ErrWikiReleaseInvalidAuthorization, name)
		}
	}

	var authorization types.PublishAuthorizationV0
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&authorization); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrWikiReleaseInvalidAuthorization, err)
	}
	normalizePublishAuthorizationV0(&authorization)
	return &authorization, nil
}

func parseClosedJSONObject(
	raw []byte,
	allowed map[string]struct{},
) (map[string]json.RawMessage, error) {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	token, err := decoder.Token()
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrWikiReleaseInvalidAuthorization, err)
	}
	if delimiter, ok := token.(json.Delim); !ok || delimiter != '{' {
		return nil, fmt.Errorf("%w: expected object", ErrWikiReleaseInvalidAuthorization)
	}

	fields := make(map[string]json.RawMessage, len(allowed))
	for decoder.More() {
		token, err = decoder.Token()
		if err != nil {
			return nil, fmt.Errorf("%w: %v", ErrWikiReleaseInvalidAuthorization, err)
		}
		name, ok := token.(string)
		if !ok {
			return nil, fmt.Errorf("%w: non-string field name", ErrWikiReleaseInvalidAuthorization)
		}
		if _, ok := allowed[name]; !ok {
			return nil, fmt.Errorf("%w: unknown field %q", ErrWikiReleaseInvalidAuthorization, name)
		}
		if _, duplicate := fields[name]; duplicate {
			return nil, fmt.Errorf("%w: duplicate field %q", ErrWikiReleaseInvalidAuthorization, name)
		}
		var value json.RawMessage
		if err := decoder.Decode(&value); err != nil {
			return nil, fmt.Errorf("%w: %v", ErrWikiReleaseInvalidAuthorization, err)
		}
		fields[name] = value
	}
	if _, err := decoder.Token(); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrWikiReleaseInvalidAuthorization, err)
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) || token != nil {
		if err == nil {
			err = errors.New("trailing JSON value")
		}
		return nil, fmt.Errorf("%w: %v", ErrWikiReleaseInvalidAuthorization, err)
	}
	return fields, nil
}

// ParseHumanBatchDecisionReceiptV1 parses the closed named-human receipt.
func ParseHumanBatchDecisionReceiptV1(raw []byte) (*types.HumanBatchDecisionReceiptV1, error) {
	fields, err := parseClosedJSONObject(raw, humanBatchDecisionReceiptV1Fields)
	if err != nil {
		return nil, err
	}
	for name := range humanBatchDecisionReceiptV1Fields {
		if _, ok := fields[name]; !ok {
			return nil, fmt.Errorf("%w: missing field %q", ErrWikiReleaseInvalidAuthorization, name)
		}
	}
	var receipt types.HumanBatchDecisionReceiptV1
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&receipt); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrWikiReleaseInvalidAuthorization, err)
	}
	normalizeHumanBatchDecisionReceiptV1(&receipt)
	return &receipt, nil
}

// CanonicalHumanBatchDecisionReceiptV1 returns the exact signed JSON bytes.
func CanonicalHumanBatchDecisionReceiptV1(
	receipt *types.HumanBatchDecisionReceiptV1,
	includeSignature bool,
) ([]byte, error) {
	if receipt == nil {
		return nil, fmt.Errorf("%w: nil human decision", ErrWikiReleaseInvalidAuthorization)
	}
	canonical := *receipt
	normalizeHumanBatchDecisionReceiptV1(&canonical)
	fields := map[string]any{
		"version": canonical.Version, "decision": canonical.Decision,
		"principal_id": canonical.PrincipalID, "tenant_id": canonical.TenantID,
		"space_id": canonical.SpaceID, "raw_kb_id": canonical.RawKBID,
		"wiki_kb_id": canonical.WikiKBID, "candidate_hash": canonical.CandidateHash,
		"human_batch_hash":   canonical.HumanBatchHash,
		"review_policy_hash": canonical.ReviewPolicyHash,
		"issued_at":          canonical.IssuedAt, "expires_at": canonical.ExpiresAt,
		"nonce": canonical.Nonce, "signer_key_id": canonical.SignerKeyID,
	}
	if includeSignature {
		fields["signature"] = canonical.Signature
	}
	raw, err := json.Marshal(fields)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrWikiReleaseInvalidAuthorization, err)
	}
	return raw, nil
}

func normalizeHumanBatchDecisionReceiptV1(receipt *types.HumanBatchDecisionReceiptV1) {
	receipt.Version = norm.NFC.String(receipt.Version)
	receipt.Decision = norm.NFC.String(receipt.Decision)
	receipt.PrincipalID = norm.NFC.String(receipt.PrincipalID)
	receipt.SpaceID = norm.NFC.String(receipt.SpaceID)
	receipt.RawKBID = norm.NFC.String(receipt.RawKBID)
	receipt.WikiKBID = norm.NFC.String(receipt.WikiKBID)
	receipt.CandidateHash = norm.NFC.String(receipt.CandidateHash)
	receipt.HumanBatchHash = norm.NFC.String(receipt.HumanBatchHash)
	receipt.ReviewPolicyHash = norm.NFC.String(receipt.ReviewPolicyHash)
	receipt.Nonce = norm.NFC.String(receipt.Nonce)
	receipt.SignerKeyID = norm.NFC.String(receipt.SignerKeyID)
	receipt.Signature = norm.NFC.String(receipt.Signature)
}

// HumanBatchDecisionVerifier verifies the named-human signature boundary.
type HumanBatchDecisionVerifier interface {
	Verify(*types.HumanBatchDecisionReceiptV1) error
}

type ed25519HumanBatchDecisionVerifier struct {
	keys map[string]ed25519.PublicKey
}

// NewEd25519HumanBatchDecisionVerifier freezes the authorized human key set.
func NewEd25519HumanBatchDecisionVerifier(
	keys map[string]ed25519.PublicKey,
) HumanBatchDecisionVerifier {
	frozen := make(map[string]ed25519.PublicKey, len(keys))
	for keyID, publicKey := range keys {
		frozen[keyID] = append(ed25519.PublicKey(nil), publicKey...)
	}
	return &ed25519HumanBatchDecisionVerifier{keys: frozen}
}

func (v *ed25519HumanBatchDecisionVerifier) Verify(
	receipt *types.HumanBatchDecisionReceiptV1,
) error {
	if receipt == nil {
		return fmt.Errorf("%w: nil human decision", ErrWikiReleaseInvalidAuthorization)
	}
	publicKey, ok := v.keys[receipt.SignerKeyID]
	if !ok || len(publicKey) != ed25519.PublicKeySize {
		return fmt.Errorf("%w: unknown human signer", ErrWikiReleaseInvalidAuthorization)
	}
	signature, err := base64.RawURLEncoding.DecodeString(receipt.Signature)
	if err != nil || len(signature) != ed25519.SignatureSize {
		return fmt.Errorf("%w: malformed human signature", ErrWikiReleaseInvalidAuthorization)
	}
	signingBytes, err := CanonicalHumanBatchDecisionReceiptV1(receipt, false)
	if err != nil {
		return err
	}
	if !ed25519.Verify(publicKey, signingBytes, signature) {
		return fmt.Errorf("%w: human signature mismatch", ErrWikiReleaseInvalidAuthorization)
	}
	return nil
}

// CanonicalPublishAuthorizationV0 returns the UTF-8 canonical JSON used by
// the S0-R signature vector. Signature is omitted from signing bytes.
func CanonicalPublishAuthorizationV0(
	authorization *types.PublishAuthorizationV0,
	includeSignature bool,
) ([]byte, error) {
	if authorization == nil {
		return nil, fmt.Errorf("%w: nil authorization", ErrWikiReleaseInvalidAuthorization)
	}
	canonical := *authorization
	normalizePublishAuthorizationV0(&canonical)
	fields := map[string]any{
		"version":                   canonical.Version,
		"action":                    canonical.Action,
		"preparation_id":            canonical.PreparationID,
		"candidate_digest":          canonical.CandidateDigest,
		"manifest_digest":           canonical.ManifestDigest,
		"ready_receipt_digest":      canonical.ReadyReceiptDigest,
		"review_decision_digest":    canonical.ReviewDecisionDigest,
		"review_policy_id":          canonical.ReviewPolicyID,
		"tenant_id":                 canonical.TenantID,
		"space_id":                  canonical.SpaceID,
		"raw_kb_id":                 canonical.RawKBID,
		"wiki_kb_id":                canonical.WikiKBID,
		"expected_release_id":       canonical.ExpectedReleaseID,
		"expected_activation_epoch": canonical.ExpectedActivationEpoch,
		"expires_at":                canonical.ExpiresAt,
		"nonce":                     canonical.Nonce,
		"signer_key_id":             canonical.SignerKeyID,
	}
	if includeSignature {
		fields["signature"] = canonical.Signature
	}
	raw, err := json.Marshal(fields)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrWikiReleaseInvalidAuthorization, err)
	}
	return raw, nil
}

func normalizePublishAuthorizationV0(authorization *types.PublishAuthorizationV0) {
	authorization.Version = norm.NFC.String(authorization.Version)
	authorization.Action = norm.NFC.String(authorization.Action)
	authorization.PreparationID = norm.NFC.String(authorization.PreparationID)
	authorization.CandidateDigest = norm.NFC.String(authorization.CandidateDigest)
	authorization.ManifestDigest = norm.NFC.String(authorization.ManifestDigest)
	authorization.ReadyReceiptDigest = norm.NFC.String(authorization.ReadyReceiptDigest)
	authorization.ReviewDecisionDigest = norm.NFC.String(authorization.ReviewDecisionDigest)
	authorization.ReviewPolicyID = norm.NFC.String(authorization.ReviewPolicyID)
	authorization.SpaceID = norm.NFC.String(authorization.SpaceID)
	authorization.RawKBID = norm.NFC.String(authorization.RawKBID)
	authorization.WikiKBID = norm.NFC.String(authorization.WikiKBID)
	authorization.ExpectedReleaseID = norm.NFC.String(authorization.ExpectedReleaseID)
	authorization.Nonce = norm.NFC.String(authorization.Nonce)
	authorization.SignerKeyID = norm.NFC.String(authorization.SignerKeyID)
	authorization.Signature = norm.NFC.String(authorization.Signature)
}

// EncodeWikiReleaseSignature freezes unpadded URL-safe base64 for S0-R.
func EncodeWikiReleaseSignature(signature []byte) string {
	return base64.RawURLEncoding.EncodeToString(signature)
}

// WikiReleaseAuthorizationVerifier verifies an experimental authorization.
type WikiReleaseAuthorizationVerifier interface {
	Verify(authorization *types.PublishAuthorizationV0) error
}

type ed25519WikiReleaseAuthorizationVerifier struct {
	keys map[string]ed25519.PublicKey
}

// NewEd25519WikiReleaseAuthorizationVerifier constructs the minimal V0
// verifier. An empty key map is intentionally fail closed.
func NewEd25519WikiReleaseAuthorizationVerifier(
	keys map[string]ed25519.PublicKey,
) WikiReleaseAuthorizationVerifier {
	frozen := make(map[string]ed25519.PublicKey, len(keys))
	for keyID, publicKey := range keys {
		frozen[keyID] = append(ed25519.PublicKey(nil), publicKey...)
	}
	return &ed25519WikiReleaseAuthorizationVerifier{keys: frozen}
}

func (v *ed25519WikiReleaseAuthorizationVerifier) Verify(
	authorization *types.PublishAuthorizationV0,
) error {
	if authorization == nil {
		return fmt.Errorf("%w: nil authorization", ErrWikiReleaseInvalidAuthorization)
	}
	publicKey, ok := v.keys[authorization.SignerKeyID]
	if !ok || len(publicKey) != ed25519.PublicKeySize {
		return fmt.Errorf("%w: unknown signer", ErrWikiReleaseInvalidAuthorization)
	}
	signature, err := base64.RawURLEncoding.DecodeString(authorization.Signature)
	if err != nil || len(signature) != ed25519.SignatureSize {
		return fmt.Errorf("%w: malformed signature", ErrWikiReleaseInvalidAuthorization)
	}
	signingBytes, err := CanonicalPublishAuthorizationV0(authorization, false)
	if err != nil {
		return err
	}
	if !ed25519.Verify(publicKey, signingBytes, signature) {
		return fmt.Errorf("%w: signature mismatch", ErrWikiReleaseInvalidAuthorization)
	}
	return nil
}

// WikiReleaseAccessRequest forces every operation to carry current principal
// and exact four-part scope.
type WikiReleaseAccessRequest struct {
	Principal types.WikiReleasePrincipal
	Scope     types.WikiReleaseScope
	Operation string
}

// WikiReleaseAccessVerifier checks current binding and both KB ACLs.
type WikiReleaseAccessVerifier interface {
	VerifyWikiReleaseAccess(context.Context, WikiReleaseAccessRequest) error
}

type wikiReleaseAccessProofKey struct{}

type wikiReleaseAccessProof struct {
	Principal types.WikiReleasePrincipal
	Scope     types.WikiReleaseScope
}

// SealWikiReleaseAccess records the exact identity and dual-ACL route scope
// after the production middleware chain has authorized both KBs.
func SealWikiReleaseAccess(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
) context.Context {
	if ctx == nil {
		ctx = context.Background()
	}
	return context.WithValue(ctx, wikiReleaseAccessProofKey{}, wikiReleaseAccessProof{
		Principal: principal,
		Scope:     scope,
	})
}

type contextWikiReleaseAccessVerifier struct{}

// NewContextWikiReleaseAccessVerifier creates the explicit verifier used by
// the strict production wrapper. Missing or mismatched proofs fail closed.
func NewContextWikiReleaseAccessVerifier() WikiReleaseAccessVerifier {
	return contextWikiReleaseAccessVerifier{}
}

func (contextWikiReleaseAccessVerifier) VerifyWikiReleaseAccess(
	ctx context.Context,
	request WikiReleaseAccessRequest,
) error {
	if ctx == nil ||
		request.Principal.ID == "" ||
		request.Principal.TenantID == 0 ||
		request.Principal.SpaceID == "" ||
		request.Scope.TenantID == 0 ||
		request.Scope.SpaceID == "" ||
		request.Scope.RawKBID == "" ||
		request.Scope.WikiKBID == "" {
		return ErrWikiReleaseAccessDenied
	}
	proof, ok := ctx.Value(wikiReleaseAccessProofKey{}).(wikiReleaseAccessProof)
	if !ok ||
		proof.Principal.ID != request.Principal.ID ||
		proof.Principal.TenantID != request.Principal.TenantID ||
		proof.Principal.SpaceID != request.Principal.SpaceID ||
		!slices.Equal(
			proof.Principal.APIKeyKnowledgeBaseIDs,
			request.Principal.APIKeyKnowledgeBaseIDs,
		) ||
		proof.Scope != request.Scope ||
		request.Principal.TenantID != request.Scope.TenantID ||
		request.Principal.SpaceID != request.Scope.SpaceID {
		return ErrWikiReleaseAccessDenied
	}
	return nil
}

type defaultWikiReleaseAccessVerifier struct{}

// NewDefaultWikiReleaseAccessVerifier returns a fail-closed fallback. A caller
// must explicitly inject a verifier backed by current binding and dual KB ACL.
func NewDefaultWikiReleaseAccessVerifier() WikiReleaseAccessVerifier {
	return defaultWikiReleaseAccessVerifier{}
}

func (defaultWikiReleaseAccessVerifier) VerifyWikiReleaseAccess(
	_ context.Context,
	_ WikiReleaseAccessRequest,
) error {
	return ErrWikiReleaseAccessDenied
}

// WikiReleaseFaults are the four bounded S0-R falsification points.
type WikiReleaseFaults struct {
	Preparation func() error
	Index       func() error
	CAS         func() error
	Receipt     func() error
}

// WikiReleaseServiceOptions keeps time, identities, and bounded faults
// injectable without creating a general workflow platform.
type WikiReleaseServiceOptions struct {
	Now                   func() time.Time
	NewID                 func(kind string) string
	Faults                WikiReleaseFaults
	HumanDecisionVerifier HumanBatchDecisionVerifier
}

// WikiReleaseConflictError is the typed expected-head/CAS loser result.
type WikiReleaseConflictError struct {
	Cause error
}

func (e *WikiReleaseConflictError) Error() string {
	if e.Cause == nil {
		return ErrWikiReleaseConflict.Error()
	}
	return ErrWikiReleaseConflict.Error() + ": " + e.Cause.Error()
}

func (e *WikiReleaseConflictError) Unwrap() error { return ErrWikiReleaseConflict }

// WikiReleaseService is the isolated S0-R core, not a production Kernel.
type WikiReleaseService struct {
	repository            *wikirepository.WikiReleaseRepository
	accessVerifier        WikiReleaseAccessVerifier
	authorizationVerifier WikiReleaseAuthorizationVerifier
	humanDecisionVerifier HumanBatchDecisionVerifier
	now                   func() time.Time
	newID                 func(kind string) string
	faults                WikiReleaseFaults
}

// NewWikiReleaseService creates the bounded experimental service.
func NewWikiReleaseService(
	repository *wikirepository.WikiReleaseRepository,
	accessVerifier WikiReleaseAccessVerifier,
	authorizationVerifier WikiReleaseAuthorizationVerifier,
	options WikiReleaseServiceOptions,
) *WikiReleaseService {
	if accessVerifier == nil {
		accessVerifier = NewDefaultWikiReleaseAccessVerifier()
	}
	if authorizationVerifier == nil {
		authorizationVerifier = NewEd25519WikiReleaseAuthorizationVerifier(nil)
	}
	if options.HumanDecisionVerifier == nil {
		options.HumanDecisionVerifier = NewEd25519HumanBatchDecisionVerifier(nil)
	}
	if options.Now == nil {
		options.Now = time.Now
	}
	if options.NewID == nil {
		options.NewID = func(kind string) string {
			return kind + "-" + uuid.NewString()
		}
	}
	return &WikiReleaseService{
		repository:            repository,
		accessVerifier:        accessVerifier,
		authorizationVerifier: authorizationVerifier,
		humanDecisionVerifier: options.HumanDecisionVerifier,
		now:                   options.Now,
		newID:                 options.NewID,
		faults:                options.Faults,
	}
}

// ActivateReviewed requires a named-human whole-batch approval before the
// existing atomic activation transaction can run.
func (s *WikiReleaseService) ActivateReviewed(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	rawDecision []byte,
	rawAuthorization []byte,
) (*types.WikiReleaseReceipt, error) {
	decision, err := ParseHumanBatchDecisionReceiptV1(rawDecision)
	if err != nil {
		return nil, err
	}
	decisionCanonical, err := CanonicalHumanBatchDecisionReceiptV1(decision, true)
	if err != nil || !bytes.Equal(rawDecision, decisionCanonical) {
		return nil, fmt.Errorf("%w: non-canonical human decision", ErrWikiReleaseInvalidAuthorization)
	}
	if s.humanDecisionVerifier == nil {
		return nil, fmt.Errorf("%w: missing human verifier", ErrWikiReleaseInvalidAuthorization)
	}
	if err := s.humanDecisionVerifier.Verify(decision); err != nil {
		return nil, err
	}
	authorization, err := ParsePublishAuthorizationV0(rawAuthorization)
	if err != nil {
		return nil, err
	}
	authorizationCanonical, err := CanonicalPublishAuthorizationV0(authorization, true)
	if err != nil {
		return nil, err
	}
	authorizationDigest := digestWikiReleaseBytes(authorizationCanonical)
	scope := types.WikiReleaseScope{
		TenantID: authorization.TenantID,
		SpaceID:  authorization.SpaceID,
		RawKBID:  authorization.RawKBID,
		WikiKBID: authorization.WikiKBID,
	}
	exactRetry := false
	if existing, receiptErr := s.repository.GetReceipt(ctx, scope, authorization.Nonce); receiptErr == nil {
		if existing.AuthorizationDigest != authorizationDigest {
			return nil, &WikiReleaseConflictError{Cause: errors.New("nonce digest mismatch")}
		}
		exactRetry = true
	} else if !errors.Is(receiptErr, wikirepository.ErrWikiReleaseNotFound) {
		return nil, receiptErr
	}
	if err := validateHumanBatchDecision059(decision, principal, scope, s.now().Unix(), exactRetry); err != nil {
		return nil, err
	}
	if authorization.Action != "activate" || authorization.Nonce != decision.Nonce {
		return nil, fmt.Errorf("%w: decision activation mismatch", ErrWikiReleaseInvalidAuthorization)
	}
	preparation, err := s.repository.GetReadyPreparation(ctx, scope, authorization.PreparationID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	if preparation.CandidateDigest != decision.CandidateHash ||
		preparation.ReadyReceiptDigest != decision.HumanBatchHash ||
		preparation.ReviewPolicyID != decision.ReviewPolicyHash ||
		preparation.ReviewDecisionDigest != digestWikiReleaseBytes(decisionCanonical) {
		return nil, fmt.Errorf("%w: human decision preparation mismatch", ErrWikiReleaseInvalidAuthorization)
	}
	return s.activate(ctx, principal, rawAuthorization)
}

func validateHumanBatchDecision059(
	receipt *types.HumanBatchDecisionReceiptV1,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	now int64,
	allowExpired bool,
) error {
	if receipt.Version != "1" || (receipt.Decision != "approve" && receipt.Decision != "reject") ||
		receipt.Decision != "approve" || receipt.PrincipalID == "" || receipt.PrincipalID != principal.ID ||
		receipt.WikiReleaseScope != scope || receipt.Nonce == "" ||
		receipt.IssuedAt <= 0 || receipt.ExpiresAt <= receipt.IssuedAt || receipt.IssuedAt > now ||
		(!allowExpired && receipt.ExpiresAt <= now) ||
		!isLowerHexSHA256(receipt.CandidateHash) || !isLowerHexSHA256(receipt.HumanBatchHash) ||
		!isLowerHexSHA256(receipt.ReviewPolicyHash) {
		return fmt.Errorf("%w: invalid human decision", ErrWikiReleaseInvalidAuthorization)
	}
	return nil
}

func isLowerHexSHA256(value string) bool {
	if len(value) != sha256.Size*2 {
		return false
	}
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size && value == strings.ToLower(value)
}

// CreateDraft validates and freezes the complete canonical manifest and
// members without making them activatable or visible through Head reads.
func (s *WikiReleaseService) createDraft(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	input *types.WikiReleasePreparation,
) (*types.WikiReleasePreparation, error) {
	if input == nil || s.repository == nil {
		return nil, fmt.Errorf("%w: nil draft", ErrWikiReleaseInvalidAuthorization)
	}
	if err := s.verifyAccess(ctx, principal, input.WikiReleaseScope, "create-draft"); err != nil {
		return nil, err
	}
	if err := s.verifySpaceBinding(ctx, input.WikiReleaseScope); err != nil {
		return nil, err
	}
	if input.ID == "" || input.CandidateDigest == "" || input.ReadyReceiptDigest == "" ||
		input.ReviewPolicyID == "" || input.ReviewDecisionDigest != "" || len(input.Members) == 0 ||
		len(input.Manifest) == 0 || !json.Valid(input.Manifest) ||
		(input.Status != "" && input.Status != types.WikiReleasePreparationDraft) {
		return nil, fmt.Errorf("%w: incomplete draft", ErrWikiReleaseInvalidAuthorization)
	}
	members, err := wikiReleaseMembersPreservingOrder(input.Members)
	if err != nil {
		return nil, err
	}
	draft := *input
	draft.Members = members
	draft.Manifest = append(json.RawMessage(nil), input.Manifest...)
	draft.ManifestDigest = digestWikiReleaseBytes(draft.Manifest)
	draft.ReviewDecisionDigest = ""
	draft.Status = types.WikiReleasePreparationDraft
	draft.CreatedAt = s.now().UTC()
	head, headErr := s.repository.GetHead(ctx, draft.WikiReleaseScope)
	switch {
	case headErr == nil:
		draft.ExpectedReleaseID = head.ActiveReleaseID
		draft.ExpectedActivationEpoch = head.ActivationEpoch
	case errors.Is(headErr, wikirepository.ErrWikiReleaseNotFound):
		draft.ExpectedReleaseID = ""
		draft.ExpectedActivationEpoch = 0
	default:
		return nil, headErr
	}
	draft.PreparationDigest = digestWikiReleasePreparation(&draft)
	if err := s.repository.CreateDraft(ctx, &draft); err != nil {
		return nil, err
	}
	return &draft, nil
}

func wikiReleaseMembersPreservingOrder(
	input []types.WikiReleaseMemberSnapshot,
) ([]types.WikiReleaseMemberSnapshot, error) {
	members := append([]types.WikiReleaseMemberSnapshot(nil), input...)
	seen := make(map[string]struct{}, len(members))
	for index := range members {
		member := &members[index]
		member.Kind = norm.NFC.String(member.Kind)
		if member.Kind == "" {
			member.Kind = "page"
		}
		member.LogicalSlug = norm.NFC.String(member.LogicalSlug)
		member.RevisionID = norm.NFC.String(member.RevisionID)
		member.MemberDigest = norm.NFC.String(member.MemberDigest)
		member.Title = norm.NFC.String(member.Title)
		member.Content = norm.NFC.String(member.Content)
		member.Payload = append(json.RawMessage(nil), member.Payload...)
		if member.LogicalSlug == "" || member.RevisionID == "" || member.MemberDigest == "" ||
			!json.Valid(member.Payload) {
			return nil, fmt.Errorf("%w: invalid manifest member", ErrWikiReleaseInvalidAuthorization)
		}
		if _, exists := seen[member.LogicalSlug]; exists {
			return nil, fmt.Errorf("%w: duplicate logical slug", ErrWikiReleaseInvalidAuthorization)
		}
		seen[member.LogicalSlug] = struct{}{}
	}
	return members, nil
}

// ReviewDraft validates one canonical named-human whole-batch receipt and
// atomically promotes the same immutable Draft to Ready. Publish authorization
// and activation remain a separate operation.
func (s *WikiReleaseService) reviewDraft(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	rawDecision []byte,
) (*types.WikiReleasePreparation, error) {
	if preparationID == "" || s.repository == nil {
		return nil, fmt.Errorf("%w: missing draft", ErrWikiReleaseInvalidAuthorization)
	}
	if err := s.verifyAccess(ctx, principal, scope, "review-draft"); err != nil {
		return nil, err
	}
	draft, err := s.repository.GetDraftPreparation(ctx, scope, preparationID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	if _, err := validateSchemaWikiPreparation(
		draft, types.WikiReleasePreparationDraft, scope,
	); err != nil {
		return nil, ErrSchemaWikiPreparationInvalid
	}
	decision, err := ParseHumanBatchDecisionReceiptV1(rawDecision)
	if err != nil {
		return nil, err
	}
	canonical, err := CanonicalHumanBatchDecisionReceiptV1(decision, true)
	if err != nil || !bytes.Equal(rawDecision, canonical) {
		return nil, fmt.Errorf("%w: non-canonical human decision", ErrWikiReleaseInvalidAuthorization)
	}
	if s.humanDecisionVerifier == nil {
		return nil, fmt.Errorf("%w: missing human verifier", ErrWikiReleaseInvalidAuthorization)
	}
	if err := s.humanDecisionVerifier.Verify(decision); err != nil {
		return nil, err
	}
	if err := validateHumanBatchDecision059(decision, principal, scope, s.now().Unix(), false); err != nil {
		return nil, err
	}
	if draft.CandidateDigest != decision.CandidateHash ||
		draft.ReadyReceiptDigest != decision.HumanBatchHash ||
		draft.ReviewPolicyID != decision.ReviewPolicyHash {
		return nil, fmt.Errorf("%w: human decision draft mismatch", ErrWikiReleaseInvalidAuthorization)
	}
	reviewDigest := digestWikiReleaseBytes(canonical)
	reviewed := *draft
	reviewed.ReviewDecisionDigest = reviewDigest
	reviewed.Status = types.WikiReleasePreparationReady
	reviewed.PreparationDigest = digestWikiReleasePreparation(&reviewed)
	return s.repository.ReviewDraft(
		ctx,
		scope,
		preparationID,
		draft,
		reviewDigest,
		reviewed.PreparationDigest,
	)
}

// ReadDraftMember serves reviewer preview only from one exact Draft member
// revision. It never consults or modifies Head.
func (s *WikiReleaseService) readDraftMember(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	preparationID string,
	logicalSlug string,
	revisionID string,
) (*types.WikiReleaseMemberSnapshot, error) {
	if err := s.verifyAccess(ctx, principal, scope, "read-draft"); err != nil {
		return nil, err
	}
	draft, err := s.repository.GetDraftPreparation(ctx, scope, preparationID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	for _, member := range draft.Members {
		if member.LogicalSlug == logicalSlug && member.RevisionID == revisionID {
			copy := member
			copy.Payload = append(json.RawMessage(nil), member.Payload...)
			return &copy, nil
		}
	}
	return nil, ErrWikiReleaseNotFound
}

// Prepare validates and freezes the complete canonical manifest and members.
func (s *WikiReleaseService) Prepare(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	input *types.WikiReleasePreparation,
) (*types.WikiReleasePreparation, error) {
	if input == nil || s.repository == nil {
		return nil, fmt.Errorf("%w: nil preparation", ErrWikiReleaseInvalidAuthorization)
	}
	if err := s.verifyAccess(ctx, principal, input.WikiReleaseScope, "prepare"); err != nil {
		return nil, err
	}
	if err := s.verifySpaceBinding(ctx, input.WikiReleaseScope); err != nil {
		return nil, err
	}
	if input.ID == "" || input.CandidateDigest == "" ||
		input.ReadyReceiptDigest == "" || input.ReviewDecisionDigest == "" ||
		input.ReviewPolicyID == "" || len(input.Members) == 0 {
		return nil, fmt.Errorf("%w: incomplete preparation", ErrWikiReleaseInvalidAuthorization)
	}
	if s.faults.Preparation != nil {
		if err := s.faults.Preparation(); err != nil {
			return nil, err
		}
	}
	manifest, members, err := canonicalWikiReleaseManifest(input.Members)
	if err != nil {
		return nil, err
	}
	if s.faults.Index != nil {
		if err := s.faults.Index(); err != nil {
			return nil, err
		}
	}

	preparation := *input
	preparation.Members = members
	preparation.Manifest = manifest
	preparation.ManifestDigest = digestWikiReleaseBytes(manifest)
	preparation.PreparationDigest = digestWikiReleasePreparation(&preparation)
	preparation.Status = types.WikiReleasePreparationReady
	preparation.CreatedAt = s.now().UTC()
	if err := s.repository.CreateReadyPreparation(ctx, &preparation); err != nil {
		return nil, err
	}
	return &preparation, nil
}

func canonicalWikiReleaseManifest(
	input []types.WikiReleaseMemberSnapshot,
) ([]byte, []types.WikiReleaseMemberSnapshot, error) {
	members := append([]types.WikiReleaseMemberSnapshot(nil), input...)
	for index := range members {
		member := &members[index]
		member.Kind = norm.NFC.String(member.Kind)
		if member.Kind == "" {
			member.Kind = "page"
		}
		member.LogicalSlug = norm.NFC.String(member.LogicalSlug)
		member.RevisionID = norm.NFC.String(member.RevisionID)
		member.MemberDigest = norm.NFC.String(member.MemberDigest)
		member.Title = norm.NFC.String(member.Title)
		member.Content = norm.NFC.String(member.Content)
		if member.LogicalSlug == "" || member.RevisionID == "" ||
			member.MemberDigest == "" || !json.Valid(member.Payload) {
			return nil, nil, fmt.Errorf("%w: invalid manifest member", ErrWikiReleaseInvalidAuthorization)
		}
	}
	sort.Slice(members, func(i, j int) bool {
		return members[i].LogicalSlug < members[j].LogicalSlug
	})
	for index := 1; index < len(members); index++ {
		if members[index-1].LogicalSlug == members[index].LogicalSlug {
			return nil, nil, fmt.Errorf("%w: duplicate logical slug", ErrWikiReleaseInvalidAuthorization)
		}
	}
	manifest, err := json.Marshal(map[string]any{"members": members})
	if err != nil {
		return nil, nil, fmt.Errorf("%w: %v", ErrWikiReleaseInvalidAuthorization, err)
	}
	return manifest, members, nil
}

func digestWikiReleasePreparation(preparation *types.WikiReleasePreparation) string {
	raw, _ := json.Marshal(map[string]any{
		"candidate_digest":          preparation.CandidateDigest,
		"expected_activation_epoch": preparation.ExpectedActivationEpoch,
		"expected_release_id":       preparation.ExpectedReleaseID,
		"manifest_digest":           preparation.ManifestDigest,
		"preparation_id":            preparation.ID,
		"raw_kb_id":                 preparation.RawKBID,
		"ready_receipt_digest":      preparation.ReadyReceiptDigest,
		"review_decision_digest":    preparation.ReviewDecisionDigest,
		"review_policy_id":          preparation.ReviewPolicyID,
		"space_id":                  preparation.SpaceID,
		"tenant_id":                 preparation.TenantID,
		"wiki_kb_id":                preparation.WikiKBID,
	})
	return digestWikiReleaseBytes(raw)
}

func digestWikiReleaseBytes(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

// activate is the private atomic release/member/CAS/receipt implementation.
// Production callers must enter through ActivateReviewed.
func (s *WikiReleaseService) activate(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	rawAuthorization []byte,
) (*types.WikiReleaseReceipt, error) {
	authorization, err := ParsePublishAuthorizationV0(rawAuthorization)
	if err != nil {
		return nil, err
	}
	canonical, err := CanonicalPublishAuthorizationV0(authorization, true)
	if err != nil {
		return nil, err
	}
	authorizationDigest := digestWikiReleaseBytes(canonical)
	scope := types.WikiReleaseScope{
		TenantID: authorization.TenantID,
		SpaceID:  authorization.SpaceID,
		RawKBID:  authorization.RawKBID,
		WikiKBID: authorization.WikiKBID,
	}

	existing, receiptErr := s.repository.GetReceipt(ctx, scope, authorization.Nonce)
	switch {
	case receiptErr == nil:
		if existing.AuthorizationDigest != authorizationDigest {
			return nil, &WikiReleaseConflictError{Cause: errors.New("nonce digest mismatch")}
		}
		if err := s.verifyAccess(ctx, principal, scope, "activate-retry"); err != nil {
			return nil, err
		}
		return existing, nil
	case !errors.Is(receiptErr, wikirepository.ErrWikiReleaseNotFound):
		return nil, receiptErr
	}

	if err := s.authorizationVerifier.Verify(authorization); err != nil {
		return nil, err
	}
	if authorization.Version != "0" || authorization.Action != "activate" ||
		authorization.PreparationID == "" || authorization.CandidateDigest == "" ||
		authorization.ManifestDigest == "" || authorization.ReadyReceiptDigest == "" ||
		authorization.ReviewDecisionDigest == "" || authorization.ReviewPolicyID == "" ||
		authorization.Nonce == "" || authorization.ExpiresAt <= s.now().Unix() {
		return nil, fmt.Errorf("%w: action, scope, or expiry", ErrWikiReleaseInvalidAuthorization)
	}

	preparation, err := s.repository.GetReadyPreparation(ctx, scope, authorization.PreparationID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	if preparation.Status != types.WikiReleasePreparationReady ||
		preparation.CandidateDigest != authorization.CandidateDigest ||
		preparation.ManifestDigest != authorization.ManifestDigest ||
		preparation.ReadyReceiptDigest != authorization.ReadyReceiptDigest ||
		preparation.ReviewDecisionDigest != authorization.ReviewDecisionDigest ||
		preparation.ReviewPolicyID != authorization.ReviewPolicyID ||
		preparation.ExpectedReleaseID != authorization.ExpectedReleaseID ||
		preparation.ExpectedActivationEpoch != authorization.ExpectedActivationEpoch {
		return nil, fmt.Errorf("%w: preparation binding mismatch", ErrWikiReleaseInvalidAuthorization)
	}
	if err := s.verifyAccess(ctx, principal, scope, "activate"); err != nil {
		return nil, err
	}
	if err := s.verifyExpectedHead(ctx, scope, authorization); err != nil {
		return nil, err
	}

	activatedAt := s.now().UTC()
	release := &types.WikiRelease{
		ID:                  s.newID("release"),
		WikiReleaseScope:    scope,
		CandidateDigest:     preparation.CandidateDigest,
		ManifestDigest:      preparation.ManifestDigest,
		BaseReleaseID:       preparation.ExpectedReleaseID,
		BaseActivationEpoch: preparation.ExpectedActivationEpoch,
		PreparationID:       preparation.ID,
		CreatedAt:           activatedAt,
		ActivatedAt:         activatedAt,
	}
	receipt, err := s.repository.Activate(ctx, wikirepository.WikiReleaseActivationWrite{
		Release:                   release,
		Members:                   preparation.Members,
		ExpectedReleaseID:         authorization.ExpectedReleaseID,
		ExpectedActivationEpoch:   authorization.ExpectedActivationEpoch,
		Nonce:                     authorization.Nonce,
		AuthorizationDigest:       authorizationDigest,
		ActivatedBy:               principal.ID,
		ActivatedAt:               activatedAt,
		ActivationReceiptID:       s.newID("receipt"),
		ExpectedPreparationID:     preparation.ID,
		ExpectedPreparationDigest: preparation.PreparationDigest,
		CASFault:                  s.faults.CAS,
		ReceiptFault:              s.faults.Receipt,
	})
	if err == nil {
		return receipt, nil
	}
	return s.resolveActivationErrorForOperation(
		ctx,
		principal,
		scope,
		authorization.Nonce,
		authorizationDigest,
		err,
		"activate-retry",
	)
}

func (s *WikiReleaseService) resolveActivationError(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	nonce string,
	authorizationDigest string,
	activationErr error,
) (*types.WikiReleaseReceipt, error) {
	return s.resolveActivationErrorForOperation(
		ctx, principal, scope, nonce, authorizationDigest, activationErr, "activate-retry",
	)
}

func (s *WikiReleaseService) resolveActivationErrorForOperation(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	nonce string,
	authorizationDigest string,
	activationErr error,
	retryOperation string,
) (*types.WikiReleaseReceipt, error) {
	existing, receiptErr := s.repository.GetReceipt(ctx, scope, nonce)
	switch {
	case receiptErr == nil:
		if existing.AuthorizationDigest != authorizationDigest {
			return nil, &WikiReleaseConflictError{Cause: errors.New("nonce digest mismatch")}
		}
		if err := s.verifyAccess(ctx, principal, scope, retryOperation); err != nil {
			return nil, err
		}
		return existing, nil
	case !errors.Is(receiptErr, wikirepository.ErrWikiReleaseNotFound):
		return nil, receiptErr
	case errors.Is(activationErr, wikirepository.ErrWikiReleaseConflict):
		return nil, &WikiReleaseConflictError{Cause: activationErr}
	default:
		return nil, activationErr
	}
}

// Revert atomically CASes Head to an immutable historical Release. It does
// not create replacement releases or members.
func (s *WikiReleaseService) Revert(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	rawAuthorization []byte,
) (*types.WikiReleaseReceipt, error) {
	authorization, err := ParsePublishAuthorizationV0(rawAuthorization)
	if err != nil {
		return nil, err
	}
	canonical, err := CanonicalPublishAuthorizationV0(authorization, true)
	if err != nil {
		return nil, err
	}
	authorizationDigest := digestWikiReleaseBytes(canonical)
	scope := types.WikiReleaseScope{
		TenantID: authorization.TenantID,
		SpaceID:  authorization.SpaceID,
		RawKBID:  authorization.RawKBID,
		WikiKBID: authorization.WikiKBID,
	}
	existing, receiptErr := s.repository.GetReceipt(ctx, scope, authorization.Nonce)
	switch {
	case receiptErr == nil:
		if existing.AuthorizationDigest != authorizationDigest {
			return nil, &WikiReleaseConflictError{Cause: errors.New("nonce digest mismatch")}
		}
		if err := s.verifyAccess(ctx, principal, scope, "revert-retry"); err != nil {
			return nil, err
		}
		return existing, nil
	case !errors.Is(receiptErr, wikirepository.ErrWikiReleaseNotFound):
		return nil, receiptErr
	}
	if err := s.authorizationVerifier.Verify(authorization); err != nil {
		return nil, err
	}
	if authorization.Version != "0" || authorization.Action != "revert" ||
		authorization.PreparationID == "" || authorization.CandidateDigest == "" ||
		authorization.ManifestDigest == "" || authorization.ReadyReceiptDigest == "" ||
		authorization.ReviewDecisionDigest == "" || authorization.ReviewPolicyID == "" ||
		authorization.ExpectedReleaseID == "" || authorization.ExpectedActivationEpoch == 0 ||
		authorization.Nonce == "" || authorization.ExpiresAt <= s.now().Unix() {
		return nil, fmt.Errorf("%w: revert action, scope, or expiry", ErrWikiReleaseInvalidAuthorization)
	}
	preparation, err := s.repository.GetReadyPreparation(ctx, scope, authorization.PreparationID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	target, err := s.repository.GetReleaseByPreparation(ctx, scope, authorization.PreparationID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	if target.ID == authorization.ExpectedReleaseID ||
		target.CandidateDigest != authorization.CandidateDigest ||
		target.ManifestDigest != authorization.ManifestDigest ||
		preparation.CandidateDigest != authorization.CandidateDigest ||
		preparation.ManifestDigest != authorization.ManifestDigest ||
		preparation.ReadyReceiptDigest != authorization.ReadyReceiptDigest ||
		preparation.ReviewDecisionDigest != authorization.ReviewDecisionDigest ||
		preparation.ReviewPolicyID != authorization.ReviewPolicyID {
		return nil, fmt.Errorf("%w: historical release binding mismatch", ErrWikiReleaseInvalidAuthorization)
	}
	if err := s.verifyAccess(ctx, principal, scope, "revert"); err != nil {
		return nil, err
	}
	if err := s.verifyExpectedHead(ctx, scope, authorization); err != nil {
		return nil, err
	}
	activatedAt := s.now().UTC()
	receipt, err := s.repository.Revert(ctx, wikirepository.WikiReleaseRevertWrite{
		Scope:                   scope,
		TargetReleaseID:         target.ID,
		ExpectedReleaseID:       authorization.ExpectedReleaseID,
		ExpectedActivationEpoch: authorization.ExpectedActivationEpoch,
		Nonce:                   authorization.Nonce,
		AuthorizationDigest:     authorizationDigest,
		ActivatedBy:             principal.ID,
		ActivatedAt:             activatedAt,
		ActivationReceiptID:     s.newID("receipt"),
		CASFault:                s.faults.CAS,
		ReceiptFault:            s.faults.Receipt,
	})
	if err == nil {
		return receipt, nil
	}
	return s.resolveActivationErrorForOperation(
		ctx, principal, scope, authorization.Nonce, authorizationDigest, err, "revert-retry",
	)
}

func (s *WikiReleaseService) verifyExpectedHead(
	ctx context.Context,
	scope types.WikiReleaseScope,
	authorization *types.PublishAuthorizationV0,
) error {
	if err := s.verifySpaceBinding(ctx, scope); err != nil {
		return err
	}
	head, err := s.repository.GetHead(ctx, scope)
	switch {
	case err == nil:
		if head.ActiveReleaseID != authorization.ExpectedReleaseID ||
			head.ActivationEpoch != authorization.ExpectedActivationEpoch {
			return &WikiReleaseConflictError{Cause: errors.New("expected head mismatch")}
		}
		return nil
	case errors.Is(err, wikirepository.ErrWikiReleaseNotFound):
		if authorization.ExpectedReleaseID != "" || authorization.ExpectedActivationEpoch != 0 {
			return &WikiReleaseConflictError{Cause: errors.New("expected initial head mismatch")}
		}
		return nil
	default:
		return err
	}
}

func (s *WikiReleaseService) verifySpaceBinding(
	ctx context.Context,
	scope types.WikiReleaseScope,
) error {
	head, err := s.repository.GetHeadForSpace(ctx, scope.TenantID, scope.SpaceID)
	switch {
	case err == nil:
		if head.RawKBID != scope.RawKBID || head.WikiKBID != scope.WikiKBID {
			return &WikiReleaseConflictError{Cause: errors.New("tenant space already bound to another release head")}
		}
		return nil
	case errors.Is(err, wikirepository.ErrWikiReleaseNotFound):
		return nil
	default:
		return err
	}
}

// Current pins the request to one release ID and epoch.
func (s *WikiReleaseService) Current(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
) (types.WikiReleaseCurrent, error) {
	if err := s.verifyAccess(ctx, principal, scope, "current"); err != nil {
		return types.WikiReleaseCurrent{}, err
	}
	head, err := s.repository.GetHead(ctx, scope)
	if err != nil {
		return types.WikiReleaseCurrent{}, mapWikiReleaseRepositoryError(err)
	}
	return types.WikiReleaseCurrent{
		ReleaseID:       head.ActiveReleaseID,
		ActivationEpoch: head.ActivationEpoch,
	}, nil
}

// WikiReleasePinnedRead is an opaque request-local Head observation. Its
// fields are intentionally private so callers cannot mint historical pins.
type WikiReleasePinnedRead struct {
	scope           types.WikiReleaseScope
	releaseID       string
	activationEpoch uint64
}

// ReleaseID returns the immutable release identity for diagnostics only.
func (pin WikiReleasePinnedRead) ReleaseID() string { return pin.releaseID }

// ActivationEpoch returns the pinned epoch for diagnostics only.
func (pin WikiReleasePinnedRead) ActivationEpoch() uint64 { return pin.activationEpoch }

// BeginPinnedRead observes Head exactly once at request start.
func (s *WikiReleaseService) BeginPinnedRead(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
) (WikiReleasePinnedRead, error) {
	current, err := s.Current(ctx, principal, scope)
	if err != nil {
		return WikiReleasePinnedRead{}, err
	}
	return WikiReleasePinnedRead{
		scope:           scope,
		releaseID:       current.ReleaseID,
		activationEpoch: current.ActivationEpoch,
	}, nil
}

// ReadPinnedPage reads from the immutable release captured at request start
// and rechecks current dual ACL without consulting Head again.
func (s *WikiReleaseService) ReadPinnedPage(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	pin WikiReleasePinnedRead,
	logicalSlug string,
) (*types.WikiReleaseMemberSnapshot, error) {
	if pin.releaseID == "" || pin.activationEpoch == 0 {
		return nil, ErrWikiReleaseNotFound
	}
	return s.pinnedPage(ctx, principal, pin.scope, pin.releaseID, logicalSlug)
}

// ReadPinnedPayload returns payload from the same request pin.
func (s *WikiReleaseService) ReadPinnedPayload(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	pin WikiReleasePinnedRead,
	logicalSlug string,
) (json.RawMessage, error) {
	if pin.releaseID == "" || pin.activationEpoch == 0 {
		return nil, ErrWikiReleaseNotFound
	}
	return s.pinnedPayload(ctx, principal, pin.scope, pin.releaseID, logicalSlug)
}

// SearchPinned searches the same request pin and rechecks current dual ACL.
func (s *WikiReleaseService) SearchPinned(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	pin WikiReleasePinnedRead,
	query string,
) ([]types.WikiReleaseMemberSnapshot, error) {
	if pin.releaseID == "" || pin.activationEpoch == 0 {
		return nil, ErrWikiReleaseNotFound
	}
	return s.minimalSearch(ctx, principal, pin.scope, pin.releaseID, query)
}

// PinnedPage reads one immutable member from an explicit release ID.
func (s *WikiReleaseService) pinnedPage(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	logicalSlug string,
) (*types.WikiReleaseMemberSnapshot, error) {
	members, err := s.readMembers(ctx, principal, scope, releaseID, "pinned-page")
	if err != nil {
		return nil, err
	}
	for index := range members {
		if members[index].LogicalSlug == logicalSlug {
			member := members[index]
			return &member, nil
		}
	}
	return nil, ErrWikiReleaseNotFound
}

// PinnedPayload returns payload from the same explicit immutable release.
func (s *WikiReleaseService) pinnedPayload(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	logicalSlug string,
) (json.RawMessage, error) {
	page, err := s.pinnedPage(ctx, principal, scope, releaseID, logicalSlug)
	if err != nil {
		return nil, err
	}
	return append(json.RawMessage(nil), page.Payload...), nil
}

// MinimalSearch is release-aware and only scans immutable release members.
func (s *WikiReleaseService) minimalSearch(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	query string,
) ([]types.WikiReleaseMemberSnapshot, error) {
	members, err := s.readMembers(ctx, principal, scope, releaseID, "minimal-search")
	if err != nil {
		return nil, err
	}
	query = strings.ToLower(strings.TrimSpace(query))
	if query == "" {
		return members, nil
	}
	results := make([]types.WikiReleaseMemberSnapshot, 0, len(members))
	for _, member := range members {
		haystack := strings.ToLower(member.LogicalSlug + "\n" + member.Title + "\n" + member.Content)
		if strings.Contains(haystack, query) {
			results = append(results, member)
		}
	}
	return results, nil
}

func (s *WikiReleaseService) readMembers(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	operation string,
) ([]types.WikiReleaseMemberSnapshot, error) {
	if releaseID == "" {
		return nil, ErrWikiReleaseNotFound
	}
	if err := s.verifyAccess(ctx, principal, scope, operation); err != nil {
		return nil, err
	}
	members, err := s.repository.GetReleaseMembers(ctx, scope, releaseID)
	if err != nil {
		return nil, mapWikiReleaseRepositoryError(err)
	}
	return members, nil
}

// IsManagedWikiKB is the only Task B guard support; ordinary PUT/DELETE
// wiring remains a later task.
func (s *WikiReleaseService) IsManagedWikiKB(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
) (bool, error) {
	if err := s.verifyAccess(ctx, principal, scope, "is-managed"); err != nil {
		return false, err
	}
	return s.repository.IsManagedWikiKB(ctx, scope)
}

// IsActiveManagedWikiKB is the ordinary PUT/DELETE guard lookup. It only
// considers an activated Head and lets callers fail closed on lookup errors.
func (s *WikiReleaseService) IsActiveManagedWikiKB(
	ctx context.Context,
	tenantID uint64,
	wikiKBID string,
) (bool, error) {
	if s.repository == nil || tenantID == 0 || strings.TrimSpace(wikiKBID) == "" {
		return false, errors.New("invalid active managed wiki lookup")
	}
	return s.repository.HasActiveHeadForWikiKB(ctx, tenantID, strings.TrimSpace(wikiKBID))
}

func (s *WikiReleaseService) verifyAccess(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	operation string,
) error {
	if s.accessVerifier == nil {
		return ErrWikiReleaseAccessDenied
	}
	if err := s.accessVerifier.VerifyWikiReleaseAccess(ctx, WikiReleaseAccessRequest{
		Principal: principal,
		Scope:     scope,
		Operation: operation,
	}); err != nil {
		if errors.Is(err, ErrWikiReleaseAccessDenied) {
			return err
		}
		return fmt.Errorf("%w: %v", ErrWikiReleaseAccessDenied, err)
	}
	return nil
}

func mapWikiReleaseRepositoryError(err error) error {
	switch {
	case errors.Is(err, wikirepository.ErrWikiReleaseNotFound):
		return ErrWikiReleaseNotFound
	case errors.Is(err, wikirepository.ErrWikiReleaseConflict):
		return &WikiReleaseConflictError{Cause: err}
	default:
		return err
	}
}
