package handler

import (
	"encoding/json"
	stderrors "errors"
	"io"
	"net/http"
	"strings"

	"github.com/Tencent/WeKnora/internal/application/service"
	apperrors "github.com/Tencent/WeKnora/internal/errors"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
)

const maxWikiReleaseAuthorizationBytes = 1 << 20

const (
	wikiReleaseWikiACLEvidenceKey = "wiki_release.wiki_acl_evidence"
	wikiReleaseRawACLEvidenceKey  = "wiki_release.raw_acl_evidence"
)

type wikiReleaseACLEvidence struct {
	KBID string
}

// WikiReleaseHandler exposes only the bounded S0-R release surface.
type WikiReleaseHandler struct {
	releaseService *service.WikiReleaseService
}

// NewWikiReleaseHandler constructs the explicitly injected release handler.
func NewWikiReleaseHandler(releaseService *service.WikiReleaseService) *WikiReleaseHandler {
	return &WikiReleaseHandler{releaseService: releaseService}
}

type wikiReleasePreparationRequest struct {
	PreparationID           string                            `json:"preparation_id"`
	CandidateDigest         string                            `json:"candidate_digest"`
	ReadyReceiptDigest      string                            `json:"ready_receipt_digest"`
	ReviewDecisionDigest    string                            `json:"review_decision_digest"`
	ReviewPolicyID          string                            `json:"review_policy_id"`
	ExpectedReleaseID       string                            `json:"expected_release_id"`
	ExpectedActivationEpoch uint64                            `json:"expected_activation_epoch"`
	Members                 []types.WikiReleaseMemberSnapshot `json:"members"`
}

func (h *WikiReleaseHandler) requestIdentity(
	c *gin.Context,
) (types.WikiReleasePrincipal, types.WikiReleaseScope, error) {
	if c == nil || c.Request == nil {
		return types.WikiReleasePrincipal{}, types.WikiReleaseScope{}, service.ErrWikiReleaseAccessDenied
	}
	tenantValue, ok := c.Get(types.TenantIDContextKey.String())
	callerTenantID, tenantOK := tenantValue.(uint64)
	contextPrincipal, contextOK := types.PrincipalFromContext(c.Request.Context())
	keyValue, keyOK := c.Get(types.PrincipalContextKey.String())
	keyPrincipal, principalOK := keyValue.(types.Principal)
	keyPrincipal = keyPrincipal.Normalize()
	if !ok || !tenantOK || callerTenantID == 0 ||
		!contextOK || !keyOK || !principalOK ||
		keyPrincipal != contextPrincipal.Normalize() {
		return types.WikiReleasePrincipal{}, types.WikiReleaseScope{}, service.ErrWikiReleaseAccessDenied
	}

	scope := types.WikiReleaseScope{
		TenantID: callerTenantID,
		SpaceID:  strings.TrimSpace(c.Param("space_id")),
		RawKBID:  strings.TrimSpace(c.Param("raw_kb_id")),
		WikiKBID: strings.TrimSpace(c.Param("kb_id")),
	}
	if scope.SpaceID == "" || scope.RawKBID == "" || scope.WikiKBID == "" {
		return types.WikiReleasePrincipal{}, types.WikiReleaseScope{}, service.ErrWikiReleaseAccessDenied
	}
	if err := types.AuthorizeTenantAPIKeyKnowledgeBases(
		c.Request.Context(),
		scope.RawKBID,
		scope.WikiKBID,
	); err != nil {
		return types.WikiReleasePrincipal{}, types.WikiReleaseScope{}, service.ErrWikiReleaseAccessDenied
	}

	principal := types.WikiReleasePrincipal{
		ID:       contextPrincipal.StorageID(),
		TenantID: callerTenantID,
		SpaceID:  scope.SpaceID,
	}
	if apiKeyScope, exists := types.TenantAPIKeyScopeFromContext(c.Request.Context()); exists {
		principal.APIKeyKnowledgeBaseIDs = append(
			[]string(nil),
			apiKeyScope.KnowledgeBaseIDs...,
		)
	}
	return principal, scope, nil
}

// RecordWikiAccessEvidence records only an exact successful Wiki KB access
// resolution. RBAC rollout fail-open paths do not produce this evidence.
func (h *WikiReleaseHandler) RecordWikiAccessEvidence() gin.HandlerFunc {
	return recordWikiReleaseACLEvidence("kb_id", wikiReleaseWikiACLEvidenceKey)
}

// RecordRawAccessEvidence records only an exact successful RAW KB access
// resolution. A stale Wiki resolution cannot satisfy the RAW marker.
func (h *WikiReleaseHandler) RecordRawAccessEvidence() gin.HandlerFunc {
	return recordWikiReleaseACLEvidence("raw_kb_id", wikiReleaseRawACLEvidenceKey)
}

func recordWikiReleaseACLEvidence(param string, evidenceKey string) gin.HandlerFunc {
	return func(c *gin.Context) {
		expectedKBID := strings.TrimSpace(c.Param(param))
		access, ok := middleware.KBAccessFromContext(c)
		if !ok || access == nil || access.KnowledgeBase == nil ||
			expectedKBID == "" || access.KnowledgeBase.ID != expectedKBID {
			writeWikiReleaseError(c, service.ErrWikiReleaseAccessDenied)
			c.Abort()
			return
		}
		c.Set(evidenceKey, wikiReleaseACLEvidence{KBID: expectedKBID})
		c.Next()
	}
}

// SealAccess runs only after both strict production ACL evidence recorders.
// Direct calls and RBAC rollout fail-open paths therefore fail closed.
func (h *WikiReleaseHandler) SealAccess() gin.HandlerFunc {
	return func(c *gin.Context) {
		principal, scope, err := h.requestIdentity(c)
		if err != nil {
			writeWikiReleaseError(c, err)
			c.Abort()
			return
		}
		wikiEvidence, wikiOK := c.Get(wikiReleaseWikiACLEvidenceKey)
		rawEvidence, rawOK := c.Get(wikiReleaseRawACLEvidenceKey)
		wikiACL, wikiTypeOK := wikiEvidence.(wikiReleaseACLEvidence)
		rawACL, rawTypeOK := rawEvidence.(wikiReleaseACLEvidence)
		if !wikiOK || !rawOK || !wikiTypeOK || !rawTypeOK ||
			wikiACL.KBID != scope.WikiKBID || rawACL.KBID != scope.RawKBID {
			writeWikiReleaseError(c, service.ErrWikiReleaseAccessDenied)
			c.Abort()
			return
		}
		c.Request = c.Request.WithContext(
			service.SealWikiReleaseAccess(c.Request.Context(), principal, scope),
		)
		c.Next()
	}
}

// Prepare freezes one exact manifest under the path-derived scope.
func (h *WikiReleaseHandler) Prepare(c *gin.Context) {
	principal, scope, err := h.requestIdentity(c)
	if err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	if h == nil || h.releaseService == nil {
		writeWikiReleaseError(c, errorsUnavailableWikiReleaseService())
		return
	}
	var request wikiReleasePreparationRequest
	decoder := json.NewDecoder(c.Request.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&request); err != nil {
		writeWikiReleaseError(c, apperrors.NewBadRequestError("invalid release preparation"))
		return
	}
	if err := ensureWikiReleaseJSONEOF(decoder); err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	preparation, err := h.releaseService.Prepare(
		c.Request.Context(),
		principal,
		&types.WikiReleasePreparation{
			ID:                      request.PreparationID,
			WikiReleaseScope:        scope,
			CandidateDigest:         request.CandidateDigest,
			ReadyReceiptDigest:      request.ReadyReceiptDigest,
			ReviewDecisionDigest:    request.ReviewDecisionDigest,
			ReviewPolicyID:          request.ReviewPolicyID,
			ExpectedReleaseID:       request.ExpectedReleaseID,
			ExpectedActivationEpoch: request.ExpectedActivationEpoch,
			Members:                 request.Members,
		},
	)
	if err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": preparation})
}

func ensureWikiReleaseJSONEOF(decoder *json.Decoder) error {
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		return apperrors.NewBadRequestError("invalid trailing release request data")
	}
	return nil
}

type wikiReleaseActivationRequest struct {
	HumanDecision        json.RawMessage `json:"human_decision"`
	PublishAuthorization json.RawMessage `json:"publish_authorization"`
}

// Activate validates a closed named-human decision and atomically activates
// its separately signed exact authorization.
func (h *WikiReleaseHandler) Activate(c *gin.Context) {
	principal, _, err := h.requestIdentity(c)
	if err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	if h == nil || h.releaseService == nil {
		writeWikiReleaseError(c, errorsUnavailableWikiReleaseService())
		return
	}
	decoder := json.NewDecoder(io.LimitReader(c.Request.Body, 2*maxWikiReleaseAuthorizationBytes+1))
	decoder.DisallowUnknownFields()
	var request wikiReleaseActivationRequest
	if err := decoder.Decode(&request); err != nil ||
		len(request.HumanDecision) == 0 || len(request.PublishAuthorization) == 0 ||
		len(request.HumanDecision) > maxWikiReleaseAuthorizationBytes ||
		len(request.PublishAuthorization) > maxWikiReleaseAuthorizationBytes ||
		ensureWikiReleaseJSONEOF(decoder) != nil {
		writeWikiReleaseError(c, apperrors.NewBadRequestError("invalid release authorization"))
		return
	}
	receipt, err := h.releaseService.ActivateReviewed(
		c.Request.Context(), principal, request.HumanDecision, request.PublishAuthorization,
	)
	if err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": receipt})
}

// Current pins the caller to the sole active Head.
func (h *WikiReleaseHandler) Current(c *gin.Context) {
	principal, scope, err := h.requestIdentity(c)
	if err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	if h == nil || h.releaseService == nil {
		writeWikiReleaseError(c, errorsUnavailableWikiReleaseService())
		return
	}
	current, err := h.releaseService.Current(c.Request.Context(), principal, scope)
	if err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": current})
}

// PinnedPage pins the current Head at request start, then serves that release.
func (h *WikiReleaseHandler) PinnedPage(c *gin.Context) {
	principal, scope, err := h.requestIdentity(c)
	if err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	if h == nil || h.releaseService == nil {
		writeWikiReleaseError(c, errorsUnavailableWikiReleaseService())
		return
	}
	pin, err := h.releaseService.BeginPinnedRead(c.Request.Context(), principal, scope)
	if err == nil && strings.TrimSpace(c.Param("release_id")) != pin.ReleaseID() {
		err = &service.WikiReleaseConflictError{Cause: stderrors.New("release is not current Head")}
	}
	var page *types.WikiReleaseMemberSnapshot
	if err == nil {
		page, err = h.releaseService.ReadPinnedPage(
			c.Request.Context(), principal, pin, strings.TrimSpace(c.Param("logical_slug")),
		)
	}
	if err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": page})
}

// PinnedPayload pins the current Head at request start, then serves its payload.
func (h *WikiReleaseHandler) PinnedPayload(c *gin.Context) {
	principal, scope, err := h.requestIdentity(c)
	if err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	if h == nil || h.releaseService == nil {
		writeWikiReleaseError(c, errorsUnavailableWikiReleaseService())
		return
	}
	pin, err := h.releaseService.BeginPinnedRead(c.Request.Context(), principal, scope)
	if err == nil && strings.TrimSpace(c.Param("release_id")) != pin.ReleaseID() {
		err = &service.WikiReleaseConflictError{Cause: stderrors.New("release is not current Head")}
	}
	var payload json.RawMessage
	if err == nil {
		payload, err = h.releaseService.ReadPinnedPayload(
			c.Request.Context(), principal, pin, strings.TrimSpace(c.Param("logical_slug")),
		)
	}
	if err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": payload})
}

// MinimalSearch pins the current Head at request start and searches only it.
func (h *WikiReleaseHandler) MinimalSearch(c *gin.Context) {
	principal, scope, err := h.requestIdentity(c)
	if err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	if h == nil || h.releaseService == nil {
		writeWikiReleaseError(c, errorsUnavailableWikiReleaseService())
		return
	}
	pin, err := h.releaseService.BeginPinnedRead(c.Request.Context(), principal, scope)
	if err == nil && strings.TrimSpace(c.Param("release_id")) != pin.ReleaseID() {
		err = &service.WikiReleaseConflictError{Cause: stderrors.New("release is not current Head")}
	}
	var results []types.WikiReleaseMemberSnapshot
	if err == nil {
		results, err = h.releaseService.SearchPinned(c.Request.Context(), principal, pin, c.Query("q"))
	}
	if err != nil {
		writeWikiReleaseError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": results})
}

// RejectManagedWikiWrite blocks ordinary Wiki PUT/DELETE only after an active
// release Head exists. Lookup errors are intentionally fail closed.
func (h *WikiReleaseHandler) RejectManagedWikiWrite() gin.HandlerFunc {
	return func(c *gin.Context) {
		if h == nil || h.releaseService == nil {
			writeWikiReleaseError(c, errorsUnavailableWikiReleaseService())
			c.Abort()
			return
		}
		tenantValue, exists := c.Get(types.TenantIDContextKey.String())
		tenantID, ok := tenantValue.(uint64)
		wikiKBID := strings.TrimSpace(c.Param("kb_id"))
		if !exists || !ok || tenantID == 0 || wikiKBID == "" {
			writeWikiReleaseError(c, service.ErrWikiReleaseAccessDenied)
			c.Abort()
			return
		}
		managed, err := h.releaseService.IsActiveManagedWikiKB(
			c.Request.Context(),
			tenantID,
			wikiKBID,
		)
		if err != nil {
			writeWikiReleaseError(c, errorsUnavailableWikiReleaseService())
			c.Abort()
			return
		}
		if managed {
			writeWikiReleaseError(c, &service.WikiReleaseConflictError{
				Cause: stderrors.New("ordinary mutation rejected for release-managed Wiki KB"),
			})
			c.Abort()
			return
		}
		c.Next()
	}
}

func errorsUnavailableWikiReleaseService() error {
	return apperrors.NewServiceUnavailableError("wiki release service unavailable")
}

func writeWikiReleaseError(c *gin.Context, err error) {
	status := http.StatusInternalServerError
	message := "wiki release request failed"
	switch {
	case stderrors.Is(err, service.ErrWikiReleaseAccessDenied):
		status = http.StatusForbidden
		message = "wiki release access denied"
	case stderrors.Is(err, service.ErrWikiReleaseConflict):
		status = http.StatusConflict
		message = "wiki release conflict"
	case stderrors.Is(err, service.ErrWikiReleaseNotFound):
		status = http.StatusNotFound
		message = "wiki release not found"
	case stderrors.Is(err, service.ErrWikiReleaseInvalidAuthorization):
		status = http.StatusBadRequest
		message = "invalid wiki release authorization"
	default:
		if appError, ok := apperrors.IsAppError(err); ok {
			status = appError.HTTPCode
			message = appError.Message
		}
	}
	c.JSON(status, gin.H{
		"success": false,
		"error":   gin.H{"message": message},
	})
}
