package handler

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type sourceGuardKBService struct {
	stubKBOnlyService
	deleteErr error
}

func (s *sourceGuardKBService) DeleteKnowledgeBase(context.Context, string) error { return s.deleteErr }

func TestKBHandlerPinnedSourceDeletionReturnsConflict(t *testing.T) {
	for _, failure := range []error{
		service.ErrKnowledgeRevisionSourcePinned,
		fmt.Errorf("wrapped: %w", service.ErrKnowledgeRevisionSourcePinned),
	} {
		svc := &sourceGuardKBService{deleteErr: failure}
		svc.getByID = func(context.Context, string) (*types.KnowledgeBase, error) {
			return &types.KnowledgeBase{ID: "kb-1", TenantID: 1}, nil
		}
		router := newKBHandlerTestRouter(svc)
		router.DELETE("/knowledge-bases/:id", (&KnowledgeBaseHandler{service: svc}).DeleteKnowledgeBase)
		response := httptest.NewRecorder()
		router.ServeHTTP(response, httptest.NewRequest(http.MethodDelete, "/knowledge-bases/kb-1", nil))
		require.Equal(t, http.StatusConflict, response.Code, response.Body.String())
		require.Contains(t, response.Body.String(), service.ErrKnowledgeRevisionSourcePinned.Error())
	}
}
