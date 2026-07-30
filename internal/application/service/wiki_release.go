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

// ParsePublishAuthorizationV0 parses the experimental S0-R authorization.
func ParsePublishAuthorizationV0(raw []byte) (*types.PublishAuthorizationV0, error) {
	fields, err := parseClosedJSONObject(raw)
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

func parseClosedJSONObject(raw []byte) (map[string]json.RawMessage, error) {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	token, err := decoder.Token()
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrWikiReleaseInvalidAuthorization, err)
	}
	if delimiter, ok := token.(json.Delim); !ok || delimiter != '{' {
		return nil, fmt.Errorf("%w: expected object", ErrWikiReleaseInvalidAuthorization)
	}

	fields := make(map[string]json.RawMessage, len(publishAuthorizationV0Fields))
	for decoder.More() {
		token, err = decoder.Token()
		if err != nil {
			return nil, fmt.Errorf("%w: %v", ErrWikiReleaseInvalidAuthorization, err)
		}
		name, ok := token.(string)
		if !ok {
			return nil, fmt.Errorf("%w: non-string field name", ErrWikiReleaseInvalidAuthorization)
		}
		if _, ok := publishAuthorizationV0Fields[name]; !ok {
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
	Now    func() time.Time
	NewID  func(kind string) string
	Faults WikiReleaseFaults
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
		now:                   options.Now,
		newID:                 options.NewID,
		faults:                options.Faults,
	}
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

// Activate validates exact authorization bindings then performs one atomic
// release/member/CAS/receipt transaction.
func (s *WikiReleaseService) Activate(
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
	return s.resolveActivationError(
		ctx,
		principal,
		scope,
		authorization.Nonce,
		authorizationDigest,
		err,
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
	existing, receiptErr := s.repository.GetReceipt(ctx, scope, nonce)
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
	case errors.Is(activationErr, wikirepository.ErrWikiReleaseConflict):
		return nil, &WikiReleaseConflictError{Cause: activationErr}
	default:
		return nil, activationErr
	}
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

// PinnedPage reads one immutable member from an explicit release ID.
func (s *WikiReleaseService) PinnedPage(
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
func (s *WikiReleaseService) PinnedPayload(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	logicalSlug string,
) (json.RawMessage, error) {
	page, err := s.PinnedPage(ctx, principal, scope, releaseID, logicalSlug)
	if err != nil {
		return nil, err
	}
	return append(json.RawMessage(nil), page.Payload...), nil
}

// MinimalSearch is release-aware and only scans immutable release members.
func (s *WikiReleaseService) MinimalSearch(
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
