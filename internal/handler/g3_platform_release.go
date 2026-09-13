package handler

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"io"
	"net/http"
	"strconv"
	"time"
)

type G3PlatformAutomatedDraftCreator interface {
	CreateBatchConceptDraftAutomated830G3(context.Context, types.WikiReleasePrincipal, types.WikiReleaseScope, string, json.RawMessage) (*types.WikiReleasePreparation, error)
}
type G3PlatformAutomatedReleaseService interface {
	ReviewDraftAutomated(context.Context, types.WikiReleasePrincipal, types.WikiReleaseScope, string, []byte) (*types.WikiReleasePreparation, error)
	ActivateAutomated(context.Context, types.WikiReleasePrincipal, []byte, []byte) (*types.WikiReleaseReceipt, error)
}
type G3PlatformReleaseHandler struct {
	access   *WikiReleaseHandler
	drafts   G3PlatformAutomatedDraftCreator
	releases G3PlatformAutomatedReleaseService
}

func NewG3PlatformReleaseHandler(access *WikiReleaseHandler, drafts G3PlatformAutomatedDraftCreator, releases G3PlatformAutomatedReleaseService) *G3PlatformReleaseHandler {
	return &G3PlatformReleaseHandler{access: access, drafts: drafts, releases: releases}
}

// CreatePreparation accepts originals of the server compiler's candidate wire,
// not field overrides, metadata or caller-declared policy authority.
func (h *G3PlatformReleaseHandler) CreatePreparation(c *gin.Context) {
	p, scope, ok := h.request(c, h != nil && h.drafts != nil)
	if !ok {
		return
	}
	raw, err := readG3PlatformReleaseBody(c, maxSchemaWikiRequestBytes)
	if err != nil {
		writeG3PlatformReleaseError(c, err)
		return
	}
	fields, err := closedG3PlatformReleaseObject(raw, "preparation_id", "bundle")
	var id string
	if err != nil || json.Unmarshal(fields["preparation_id"], &id) != nil || !validG3PlatformPathID(id) || !g3PlatformJSONObject(fields["bundle"]) {
		writeG3PlatformReleaseError(c, service.ErrWikiReleaseInvalidAuthorization)
		return
	}
	result, err := h.drafts.CreateBatchConceptDraftAutomated830G3(c.Request.Context(), p, scope, id, fields["bundle"])
	if err != nil {
		writeG3PlatformReleaseError(c, err)
		return
	}
	if result == nil {
		writeG3PlatformReleaseError(c, errG3PlatformReleaseUnavailable)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": g3PlatformPreparationMetadataOf(result)})
}

func (h *G3PlatformReleaseHandler) ReviewPreparation(c *gin.Context) {
	p, scope, ok := h.request(c, h != nil && h.releases != nil)
	if !ok {
		return
	}
	id := c.Param("preparation_id")
	if !validG3PlatformPathID(id) {
		writeG3PlatformReleaseError(c, service.ErrWikiReleaseInvalidAuthorization)
		return
	}
	raw, err := readG3PlatformReleaseBody(c, maxWikiReleaseAuthorizationBytes)
	if err != nil {
		writeG3PlatformReleaseError(c, err)
		return
	}
	decision, err := parseG3PlatformSystemDecision(raw, scope)
	if err != nil || decision.PreparationID != id {
		writeG3PlatformReleaseError(c, service.ErrWikiReleaseInvalidAuthorization)
		return
	}
	result, err := h.releases.ReviewDraftAutomated(c.Request.Context(), p, scope, id, raw)
	if err != nil {
		writeG3PlatformReleaseError(c, err)
		return
	}
	if result == nil {
		writeG3PlatformReleaseError(c, errG3PlatformReleaseUnavailable)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": g3PlatformPreparationMetadataOf(result)})
}

func (h *G3PlatformReleaseHandler) Activate(c *gin.Context) {
	p, scope, ok := h.request(c, h != nil && h.releases != nil)
	if !ok {
		return
	}
	raw, err := readG3PlatformReleaseBody(c, 2*maxWikiReleaseAuthorizationBytes)
	if err != nil {
		writeG3PlatformReleaseError(c, err)
		return
	}
	fields, err := closedG3PlatformReleaseObject(raw, "decision", "authorization")
	if err != nil || len(fields["decision"]) > maxWikiReleaseAuthorizationBytes || len(fields["authorization"]) > maxWikiReleaseAuthorizationBytes {
		writeG3PlatformReleaseError(c, service.ErrWikiReleaseInvalidAuthorization)
		return
	}
	if _, err := parseG3PlatformSystemDecision(fields["decision"], scope); err != nil {
		writeG3PlatformReleaseError(c, err)
		return
	}
	auth, err := service.ParsePublishAuthorizationV0(fields["authorization"])
	if err != nil {
		writeG3PlatformReleaseError(c, service.ErrWikiReleaseInvalidAuthorization)
		return
	}
	canonical, err := service.CanonicalPublishAuthorizationV0(auth, true)
	if err != nil || !bytes.Equal(canonical, fields["authorization"]) ||
		auth.TenantID != scope.TenantID || auth.SpaceID != scope.SpaceID || auth.RawKBID != scope.RawKBID || auth.WikiKBID != scope.WikiKBID {
		writeG3PlatformReleaseError(c, service.ErrWikiReleaseInvalidAuthorization)
		return
	}
	// RawMessage preserves the signed object bytes. Never marshal parsed DTOs
	// back into the request sent to the authority service.
	result, err := h.releases.ActivateAutomated(c.Request.Context(), p, fields["decision"], fields["authorization"])
	if err != nil {
		writeG3PlatformReleaseError(c, err)
		return
	}
	if result == nil {
		writeG3PlatformReleaseError(c, errG3PlatformReleaseUnavailable)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": result})
}

func (h *G3PlatformReleaseHandler) request(c *gin.Context, ready bool) (types.WikiReleasePrincipal, types.WikiReleaseScope, bool) {
	var p types.WikiReleasePrincipal
	var scope types.WikiReleaseScope
	if h == nil || h.access == nil || !ready {
		writeG3PlatformReleaseError(c, errG3PlatformReleaseUnavailable)
		return p, scope, false
	}
	p, scope, err := h.access.requestIdentity(c)
	if err != nil {
		writeG3PlatformReleaseError(c, service.ErrWikiReleaseAccessDenied)
		return p, scope, false
	}
	terminal, ok := types.PrincipalFromContext(c.Request.Context())
	key, keyOK := types.TenantAPIKeyScopeFromContext(c.Request.Context())
	if !ok || terminal.Type != types.PrincipalAPITenant || terminal.ID != strconv.FormatUint(scope.TenantID, 10) ||
		!keyOK || key.KeyID == 0 || key.FullAccess || key.IsPlatform() || scope.RawKBID == scope.WikiKBID || len(key.KnowledgeBaseIDs) != 2 ||
		!key.AllowsKnowledgeBase(scope.RawKBID) || !key.AllowsKnowledgeBase(scope.WikiKBID) {
		writeG3PlatformReleaseError(c, service.ErrWikiReleaseAccessDenied)
		return p, scope, false
	}
	if err := service.NewContextWikiReleaseAccessVerifier().VerifyWikiReleaseAccess(c.Request.Context(), service.WikiReleaseAccessRequest{Principal: p, Scope: scope, Operation: "platform-release"}); err != nil {
		writeG3PlatformReleaseError(c, service.ErrWikiReleaseAccessDenied)
		return p, scope, false
	}
	return p, scope, true
}

var (
	errG3PlatformReleaseUnavailable  = errors.New("platform release unavailable")
	errG3PlatformReleaseBodyTooLarge = errors.New("platform release body too large")
)

func readG3PlatformReleaseBody(c *gin.Context, limit int) ([]byte, error) {
	if c == nil || c.Request == nil || c.Request.Body == nil {
		return nil, service.ErrWikiReleaseInvalidAuthorization
	}
	if c.Request.ContentLength > int64(limit) {
		return nil, errG3PlatformReleaseBodyTooLarge
	}
	raw, err := io.ReadAll(io.LimitReader(c.Request.Body, int64(limit)+1))
	if len(raw) > limit {
		return nil, errG3PlatformReleaseBodyTooLarge
	}
	if err != nil || len(raw) == 0 {
		return nil, service.ErrWikiReleaseInvalidAuthorization
	}
	return raw, nil
}

func g3PlatformJSONObject(raw []byte) bool {
	trimmed := bytes.TrimSpace(raw)
	return len(trimmed) >= 2 && trimmed[0] == '{' && trimmed[len(trimmed)-1] == '}'
}

// Validate duplicate keys at every depth before extracting the closed envelope.
// This keeps ambiguous JSON out of both signed objects and candidate bundles.
func closedG3PlatformReleaseObject(raw []byte, names ...string) (map[string]json.RawMessage, error) {
	if !g3PlatformJSONObject(raw) {
		return nil, service.ErrWikiReleaseInvalidAuthorization
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err := distinctG3PlatformJSONValue(decoder, 0); err != nil || ensureWikiReleaseJSONEOF(decoder) != nil {
		return nil, service.ErrWikiReleaseInvalidAuthorization
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil || len(fields) != len(names) {
		return nil, service.ErrWikiReleaseInvalidAuthorization
	}
	for _, name := range names {
		value, ok := fields[name]
		if !ok || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return nil, service.ErrWikiReleaseInvalidAuthorization
		}
	}
	return fields, nil
}

func distinctG3PlatformJSONValue(decoder *json.Decoder, depth int) error {
	if depth > 128 {
		return service.ErrWikiReleaseInvalidAuthorization
	}
	token, err := decoder.Token()
	if err != nil {
		return err
	}
	delimiter, container := token.(json.Delim)
	if !container {
		return nil
	}
	switch delimiter {
	case '{':
		seen := map[string]bool{}
		for decoder.More() {
			token, err := decoder.Token()
			if err != nil {
				return err
			}
			key, ok := token.(string)
			if !ok || seen[key] {
				return service.ErrWikiReleaseInvalidAuthorization
			}
			seen[key] = true
			if err := distinctG3PlatformJSONValue(decoder, depth+1); err != nil {
				return err
			}
		}
	case '[':
		for decoder.More() {
			if err := distinctG3PlatformJSONValue(decoder, depth+1); err != nil {
				return err
			}
		}
	default:
		return service.ErrWikiReleaseInvalidAuthorization
	}
	closing, err := decoder.Token()
	if err != nil || (delimiter == '{' && closing != json.Delim('}')) || (delimiter == '[' && closing != json.Delim(']')) {
		return service.ErrWikiReleaseInvalidAuthorization
	}
	return nil
}

func parseG3PlatformSystemDecision(raw []byte, scope types.WikiReleaseScope) (*service.SystemPolicyDecisionReceiptV1, error) {
	decision, err := service.ParseSystemPolicyDecisionReceiptV1(raw)
	if err != nil {
		return nil, service.ErrWikiReleaseInvalidAuthorization
	}
	canonical, err := service.CanonicalSystemPolicyDecisionReceiptV1(decision, true)
	if err != nil || !bytes.Equal(canonical, raw) || decision.WikiReleaseScope != scope {
		return nil, service.ErrWikiReleaseInvalidAuthorization
	}
	return decision, nil
}

func writeG3PlatformReleaseError(c *gin.Context, err error) {
	switch {
	case errors.Is(err, errG3PlatformReleaseBodyTooLarge):
		c.JSON(http.StatusRequestEntityTooLarge, gin.H{"success": false, "error": gin.H{"message": "platform release request too large"}})
	case errors.Is(err, errG3PlatformReleaseUnavailable):
		writeWikiReleaseError(c, errorsUnavailableWikiReleaseService())
	case errors.Is(err, service.ErrSchemaWikiPreparationInvalid):
		writeWikiReleaseError(c, service.ErrWikiReleaseInvalidAuthorization)
	default:
		// Preserve public status sentinels without leaking wrapped backend errors,
		// app-error messages, credentials or filesystem paths.
		for _, known := range []error{service.ErrWikiReleaseAccessDenied, service.ErrWikiReleaseConflict, service.ErrWikiReleaseNotFound, service.ErrWikiReleaseInvalidAuthorization, service.ErrConceptSourceAuthorityUnavailable830G2} {
			if errors.Is(err, known) {
				writeWikiReleaseError(c, known)
				return
			}
		}
		writeWikiReleaseError(c, errors.New("platform release failed"))
	}
}

// Preparation responses contain only the immutable identities required for the
// next signed step. Candidate bodies and model audit data stay in their stores.
type g3PlatformPreparationMetadata struct {
	types.WikiReleaseScope
	PreparationID           string    `json:"preparation_id"`
	Status                  string    `json:"status"`
	PreparationDigest       string    `json:"preparation_digest"`
	CandidateDigest         string    `json:"candidate_digest"`
	ManifestDigest          string    `json:"manifest_digest"`
	ReadyReceiptDigest      string    `json:"ready_receipt_digest"`
	ReviewDecisionDigest    string    `json:"review_decision_digest"`
	ReviewPolicyID          string    `json:"review_policy_id"`
	ExpectedReleaseID       string    `json:"expected_release_id"`
	ExpectedActivationEpoch uint64    `json:"expected_activation_epoch"`
	CreatedAt               time.Time `json:"created_at"`
}

func g3PlatformPreparationMetadataOf(p *types.WikiReleasePreparation) g3PlatformPreparationMetadata {
	return g3PlatformPreparationMetadata{WikiReleaseScope: p.WikiReleaseScope, PreparationID: p.ID, Status: p.Status, PreparationDigest: p.PreparationDigest, CandidateDigest: p.CandidateDigest, ManifestDigest: p.ManifestDigest, ReadyReceiptDigest: p.ReadyReceiptDigest, ReviewDecisionDigest: p.ReviewDecisionDigest, ReviewPolicyID: p.ReviewPolicyID, ExpectedReleaseID: p.ExpectedReleaseID, ExpectedActivationEpoch: p.ExpectedActivationEpoch, CreatedAt: p.CreatedAt}
}
