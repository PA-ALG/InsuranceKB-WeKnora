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

// U-1: registration no longer panics without the owner lookup (upstream's
// route-table tests register with partial guards); the routes fail closed instead.
func TestNativeWikiRegistrationWithoutOwnerLookupFailsClosed(t *testing.T) {
	require.NotPanics(t, func() {
		RegisterWikiPageRoutes(gin.New().Group("/api/v1"), &handler.WikiPageHandler{},
			&rbacGuards{kbService: scopedOnlyKBLookup{}}, &stubClassifier{})
	})
	var lookup managed.KnowledgeBaseLookup
	_, err := managed.ForKnowledgeBaseOwner(&stubClassifier{}, lookup).Classify(context.Background(), 7, "kb")
	var writeErr *managed.WriteError
	require.ErrorAs(t, err, &writeErr)
	require.Equal(t, managed.ErrorCodeClassificationUnavailable, writeErr.Code)
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

// The release-custody owner lookup reads by ID only; upstream's wiki route
// fixture answers it from its tenant-scoped lookup.
func (s *stubWikiKBLookup) GetKnowledgeBaseByIDOnly(ctx context.Context, id string) (*types.KnowledgeBase, error) {
	return s.GetKnowledgeBaseByID(ctx, id)
}
