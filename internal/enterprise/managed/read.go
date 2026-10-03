package managed

import (
	"context"
	"net/http"
	"strings"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
)

// ReadError carries a public reason without leaking classification internals.
type ReadError struct{ Code string }

func (e *ReadError) Error() string {
	if e.Code == ErrorCodeReleaseManaged {
		return e.Code + ": 该知识库由发布链管理，请通过发布版本读取"
	}
	return e.Code + ": 知识库受管状态暂时无法确认，请稍后重试"
}

// Custody is the public status of a KB, not a second release authority.
type Custody struct {
	Managed bool  `json:"managed"`
	Kind    Kind  `json:"kind"`
	State   State `json:"state"`
}

// LookupCustody validates classification before any native read can proceed.
func LookupCustody(ctx context.Context, c Classifier, tenant uint64, kbID string) (Custody, error) {
	unavailable := &ReadError{Code: ErrorCodeClassificationUnavailable}
	if c == nil || tenant == 0 || strings.TrimSpace(kbID) == "" {
		return Custody{}, unavailable
	}
	role, err := c.Classify(ctx, tenant, strings.TrimSpace(kbID))
	if err != nil {
		return Custody{}, unavailable
	}
	if role.Kind == KindWiki || role.Kind == KindRaw || role.State == StatePending || role.State == StateActive {
		return Custody{Managed: true, Kind: role.Kind, State: role.State}, nil
	}
	if (role.Kind != "" && role.Kind != KindNone) || (role.State != "" && role.State != StateUnmanaged) {
		return Custody{}, unavailable
	}
	return Custody{Kind: KindNone, State: StateUnmanaged}, nil
}

// CheckRead rejects native content reads for any release-managed KB.
func CheckRead(ctx context.Context, c Classifier, tenant uint64, kbID string) error {
	status, err := LookupCustody(ctx, c, tenant, kbID)
	if err != nil {
		return err
	}
	if status.Managed {
		return &ReadError{Code: ErrorCodeReleaseManaged}
	}
	return nil
}

// CustodyHandler must be mounted after Viewer and KBAccessRead; those guards
// authorize the caller and establish the KB owner's tenant context.
func CustodyHandler(classifier Classifier) gin.HandlerFunc {
	return func(c *gin.Context) {
		tenant, ok := types.TenantIDFromContext(c.Request.Context())
		if !ok {
			tenant = 0
		}
		status, err := LookupCustody(c.Request.Context(), classifier, tenant, c.Param("kb_id"))
		if err != nil {
			c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{"success": false, "error": gin.H{
				"code": ErrorCodeClassificationUnavailable, "message": err.Error(),
			}})
			return
		}
		c.JSON(http.StatusOK, status)
	}
}
