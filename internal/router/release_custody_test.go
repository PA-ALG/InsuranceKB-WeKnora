package router

import (
	"context"
	"errors"
	"net/http"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/handler"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type scopedOnlyKBLookup struct{}

func (scopedOnlyKBLookup) GetKnowledgeBaseByID(context.Context, string) (*types.KnowledgeBase, error) {
	return nil, nil
}

func TestNativeWikiRegistrationRequiresOwnerLookup(t *testing.T) {
	require.Panics(t, func() {
		RegisterWikiPageRoutesWithRelease(gin.New().Group("/api/v1"), &handler.WikiPageHandler{}, nil,
			&rbacGuards{kbService: scopedOnlyKBLookup{}}, &stubClassifier{})
	})
}

func TestReleaseCustodyRoute(t *testing.T) {
	for _, tc := range []struct {
		name   string
		role   managed.Role
		err    error
		status int
		body   string
	}{
		{
			"managed",
			managed.Role{Kind: managed.KindRaw, State: managed.StatePending},
			nil, 200,
			`{"managed":true,"kind":"raw","state":"pending"}`,
		},
		{
			"plain",
			managed.Role{Kind: managed.KindNone, State: managed.StateUnmanaged},
			nil, 200,
			`{"managed":false,"kind":"none","state":"unmanaged"}`,
		},
		{"unavailable", managed.Role{}, errors.New("private database detail"), 503, ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := &stubClassifier{roles: map[string]managed.Role{"kb-allowed": tc.role}, err: tc.err}
			engine := newGuardedWikiEngine(t, c)
			rec := serve(engine, http.MethodGet, "/api/v1/knowledgebase/kb-allowed/release-custody")
			require.Equal(t, tc.status, rec.Code, rec.Body.String())
			if tc.body != "" {
				require.JSONEq(t, tc.body, rec.Body.String())
			} else {
				require.Equal(t, managed.ErrorCodeClassificationUnavailable, errorCode(t, rec))
				require.NotContains(t, rec.Body.String(), "private database detail")
			}
		})
	}
}

func TestReleaseCustodyRequiresKBAccess(t *testing.T) {
	classifier := &stubClassifier{}
	engine := newGuardedWikiEngine(t, classifier)
	rec := serve(engine, http.MethodGet, "/api/v1/knowledgebase/missing/release-custody")
	require.NotEqual(t, http.StatusOK, rec.Code)
	require.Empty(t, classifier.calls, "classify only after KB access is authorized")
}

// Only router registration is exercised; unused service methods stay unset.
type routeRegistrationKBService struct {
	interfaces.KnowledgeBaseService
}

func (*routeRegistrationKBService) GetKnowledgeBaseByIDOnly(
	ctx context.Context, id string,
) (*types.KnowledgeBase, error) {
	return tenantKBLookupFixture().GetKnowledgeBaseByIDOnly(ctx, id)
}
