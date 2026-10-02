package managed

import (
	"context"
	"net/http"
	"strings"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/gin-gonic/gin"
	"go.uber.org/dig"
)

// Error codes are shared by HTTP, Agent and MCP write denials.
const (
	ErrorCodeReleaseManaged            = "RELEASE_MANAGED_KB"
	ErrorCodeClassificationUnavailable = "MANAGED_KB_CLASSIFICATION_UNAVAILABLE"
)

// WriteError carries a public denial code without exposing private query errors.
type WriteError struct{ Code string }

func (e *WriteError) Error() string { return e.Code + ": " + e.message() }
func (e *WriteError) message() string {
	if e.Code == ErrorCodeReleaseManaged {
		return "该知识库内容由发布链管理，请经编译与审核流程修改"
	}
	return "知识库受管状态暂时无法确认，请稍后重试"
}

// CheckWrite gives HTTP, Agent and MCP one denial policy and error vocabulary.
func CheckWrite(ctx context.Context, classifier Classifier, tenantID uint64, kbID string) error {
	if err := CheckRead(ctx, classifier, tenantID, kbID); err != nil {
		return &WriteError{Code: err.(*ReadError).Code}
	}
	return nil
}

// GuardWikiWrite rejects managed targets before normal route permission checks.
func GuardWikiWrite(classifier Classifier) gin.HandlerFunc {
	return func(c *gin.Context) {
		tenant, exists := c.Get(types.TenantIDContextKey.String())
		tenantID, valid := tenant.(uint64)
		if !exists || !valid || tenantID == 0 {
			reject(c, http.StatusServiceUnavailable, &WriteError{Code: ErrorCodeClassificationUnavailable})
			return
		}
		kbID := strings.TrimSpace(c.Param("kb_id"))
		if kbID == "" {
			c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{
				"success": false,
				"error":   gin.H{"code": "INVALID_KNOWLEDGE_BASE", "message": "knowledge base ID is required"},
			})
			return
		}
		if err := CheckWrite(c.Request.Context(), classifier, tenantID, kbID); err != nil {
			failure := err.(*WriteError)
			status := http.StatusServiceUnavailable
			if failure.Code == ErrorCodeReleaseManaged {
				status = http.StatusConflict
			}
			reject(c, status, failure)
			return
		}
		c.Next()
	}
}

func reject(c *gin.Context, status int, err *WriteError) {
	c.AbortWithStatusJSON(status, gin.H{"success": false, "error": gin.H{"code": err.Code, "message": err.message()}})
}

// KnowledgeBaseLookup resolves the target owner without granting caller access.
type KnowledgeBaseLookup interface {
	GetKnowledgeBaseByIDOnly(context.Context, string) (*types.KnowledgeBase, error)
}

type knowledgeBaseOwnerClassifier struct {
	classifier Classifier
	lookup     KnowledgeBaseLookup
}

// ForKnowledgeBaseOwner resolves shared targets before applying the custody
// policy. It leaves caller context intact for the subsequent permission checks.
func ForKnowledgeBaseOwner(classifier Classifier, lookup KnowledgeBaseLookup) Classifier {
	return &knowledgeBaseOwnerClassifier{classifier: classifier, lookup: lookup}
}

func (c *knowledgeBaseOwnerClassifier) Classify(ctx context.Context, tenantID uint64, kbID string) (Role, error) {
	if tenantID == 0 || c.classifier == nil || c.lookup == nil {
		return Role{}, &WriteError{Code: ErrorCodeClassificationUnavailable}
	}
	kb, err := c.lookup.GetKnowledgeBaseByIDOnly(ctx, kbID)
	if err != nil || kb == nil || kb.ID != kbID || kb.TenantID == 0 {
		return Role{}, &WriteError{Code: ErrorCodeClassificationUnavailable}
	}
	return c.classifier.Classify(ctx, kb.TenantID, kb.ID)
}

type classifiedWikiService struct {
	interfaces.WikiPageService
	classifier Classifier
	lookup     KnowledgeBaseLookup
}

// WrapWikiService uses the existing service extension point to reach tools
// without changing their constructors or the Agent's registration code.
func WrapWikiService(
	service interfaces.WikiPageService, classifier Classifier, lookup KnowledgeBaseLookup,
) interfaces.WikiPageService {
	return &classifiedWikiService{WikiPageService: service, classifier: classifier, lookup: lookup}
}

// CheckWikiWrite classifies the authoritative owner of a shared KB, rather
// than querying custody under the caller's tenant and accidentally allowing it.
func (s *classifiedWikiService) CheckWikiWrite(ctx context.Context, kbID string) error {
	unavailable := &WriteError{Code: ErrorCodeClassificationUnavailable}
	tenant, ok := types.TenantIDFromContext(ctx)
	if !ok || tenant == 0 {
		return unavailable
	}
	return CheckWrite(ctx, ForKnowledgeBaseOwner(s.classifier, s.lookup), tenant, kbID)
}

// DecorateWikiService carries the same injected policy through the production DI graph.
func DecorateWikiService(
	service interfaces.WikiPageService, classifier Classifier, lookup interfaces.KnowledgeBaseService,
) interfaces.WikiPageService {
	return WrapWikiService(service, classifier, lookup)
}

// Register installs one shared classifier and the Wiki tool write boundary.
func Register(container *dig.Container) error {
	if err := container.Provide(NewDatabaseClassifier); err != nil {
		return err
	}
	return container.Decorate(DecorateWikiService)
}
