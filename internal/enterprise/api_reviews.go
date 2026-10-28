package enterprise

import (
	"net/http"
	"strings"
	"unicode/utf8"

	"github.com/gin-gonic/gin"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const maxPolicyRef = 200

// machineReviewQueue lists a Space's review queue for a full-access service key (RV6d), with the
// same summaries as the administrator session route.
func machineReviewQueue(c *gin.Context, service *release.Service) {
	p, ok := publishingRequest(c, service)
	if !ok {
		return
	}
	status := "pending"
	if values, exists := c.Request.URL.Query()["status"]; exists {
		if len(values) != 1 || values[0] == "" {
			writeError(c, &release.Error{Code: release.ErrorDecisionInvalid, Detail: "one queue status is required"})
			return
		}
		status = values[0]
	}
	items, err := service.ReviewQueue(c.Request.Context(), p, c.Param("space_id"), status)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{"items": items}})
}

// machineReviewDetail reads one candidate for a full-access service key (RV6e): the same detail
// as the administrator session route, so a machine caller can check a candidate's content before
// it closes review points.
func machineReviewDetail(c *gin.Context, service *release.Service) {
	p, ok := publishingRequest(c, service)
	if !ok {
		return
	}
	item, err := service.ReviewCandidate(c.Request.Context(), p, c.Param("space_id"), c.Param("candidate_id"))
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": item})
}

// machinePointRejection closes review points for a service key. The machine route never approves
// a point: machine-approved content goes live as a relabelled machine candidate, so published
// claims keep an honest review label. The versioned policy is kept in the stored reason because
// point decisions have no policy column (no migration in RV6d).
func machinePointRejection(c *gin.Context, service *release.Service) {
	p, ok := publishingRequest(c, service)
	if !ok {
		return
	}
	var input struct {
		Slugs     []string `json:"slugs"`
		Outcome   string   `json:"outcome"`
		Reason    string   `json:"reason"`
		PolicyRef string   `json:"policy_ref"`
	}
	err := decodeSpotCheckBody(c, &input, maxControlBody, release.ErrorDecisionInvalid,
		"slugs", "outcome", "reason", "policy_ref")
	if err != nil {
		writeError(c, err)
		return
	}
	policy, reason := strings.TrimSpace(input.PolicyRef), strings.TrimSpace(input.Reason)
	if input.Outcome != "reject" || policy == "" || utf8.RuneCountInString(policy) > maxPolicyRef || reason == "" {
		writeError(c, &release.Error{
			Code: release.ErrorDecisionInvalid, Detail: "a service key rejects points with a reason and a policy_ref",
		})
		return
	}
	result, err := service.ReviewPoints(c.Request.Context(), p, c.Param("space_id"), c.Param("candidate_id"),
		input.Slugs, "reject", reason+"（policy_ref: "+policy+"）")
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": result})
}
