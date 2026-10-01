package managed

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type classifierStub struct {
	role  Role
	err   error
	calls int
}

func (s *classifierStub) Classify(context.Context, uint64, string) (Role, error) {
	s.calls++
	return s.role, s.err
}

func TestGuardWritePreservesErrorEnvelopeAndFailsClosed(t *testing.T) {
	gin.SetMode(gin.TestMode)
	for _, tc := range []struct {
		name       string
		classifier Classifier
		tenant     any
		kb         bool
		status     int
		code       string
	}{
		{
			"pending wiki", &classifierStub{role: Role{Kind: KindWiki, State: StatePending}},
			uint64(42), true, 409, ErrorCodeReleaseManaged,
		},
		{
			"active raw", &classifierStub{role: Role{Kind: KindRaw, State: StateActive}},
			uint64(42), true, 409, ErrorCodeReleaseManaged,
		},
		{"unmanaged", &classifierStub{}, uint64(42), true, 204, ""},
		{
			"classification failed", &classifierStub{err: errors.New("private lookup details")},
			uint64(42), true, 503, ErrorCodeClassificationUnavailable,
		},
		{"classifier absent", nil, uint64(42), true, 503, ErrorCodeClassificationUnavailable},
		{"tenant absent", &classifierStub{}, nil, true, 503, ErrorCodeClassificationUnavailable},
		{"tenant zero", &classifierStub{}, uint64(0), true, 503, ErrorCodeClassificationUnavailable},
		{"tenant wrong type", &classifierStub{}, "42", true, 503, ErrorCodeClassificationUnavailable},
		{"kb absent", &classifierStub{}, uint64(42), false, 400, "INVALID_KNOWLEDGE_BASE"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := gin.New()
			r.Use(func(c *gin.Context) {
				if tc.tenant != nil {
					c.Set(types.TenantIDContextKey.String(), tc.tenant)
				}
				c.Next()
			})
			path, requestPath := "/:kb_id", "/wiki"
			if !tc.kb {
				path, requestPath = "/", "/"
			}
			calls := 0
			r.POST(path, GuardWikiWrite(tc.classifier), func(c *gin.Context) { calls++; c.Status(204) })
			rec := httptest.NewRecorder()
			r.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, requestPath, nil))
			require.Equal(t, tc.status, rec.Code)
			if tc.code != "" {
				var body struct {
					Success bool
					Error   struct{ Code, Message string }
				}
				require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &body))
				require.False(t, body.Success)
				require.Equal(t, tc.code, body.Error.Code)
				require.NotContains(t, body.Error.Message, "private lookup details")
				require.Zero(t, calls)
			} else {
				require.Equal(t, 1, calls)
			}
		})
	}
}

func TestCheckWriteUsesOneClassifier(t *testing.T) {
	for _, kind := range []Kind{KindWiki, KindRaw} {
		for _, state := range []State{StatePending, StateActive} {
			classifier := &classifierStub{role: Role{Kind: kind, State: state}}
			err := CheckWrite(context.Background(), classifier, 42, "kb")
			require.ErrorContains(t, err, ErrorCodeReleaseManaged)
			require.Equal(t, 1, classifier.calls)
		}
	}
	require.NoError(t, CheckWrite(context.Background(), &classifierStub{}, 42, "ordinary"))
	require.ErrorContains(t, CheckWrite(context.Background(), nil, 42, "kb"), ErrorCodeClassificationUnavailable)
	require.ErrorContains(t, CheckWrite(context.Background(),
		&classifierStub{err: errors.New("private lookup details")}, 42, "kb"), ErrorCodeClassificationUnavailable)
}

type (
	wikiStub  struct{ interfaces.WikiPageService }
	ownerStub struct {
		kb  *types.KnowledgeBase
		err error
	}
)

func (s ownerStub) GetKnowledgeBaseByIDOnly(context.Context, string) (*types.KnowledgeBase, error) {
	return s.kb, s.err
}

type ownerClassifier struct {
	tenant uint64
	kb     string
	role   Role
}

func (s *ownerClassifier) Classify(_ context.Context, tenant uint64, kb string) (Role, error) {
	s.tenant, s.kb = tenant, kb
	return s.role, nil
}

func TestWikiServiceGuardClassifiesAuthoritativeOwner(t *testing.T) {
	c := &ownerClassifier{role: Role{Kind: KindRaw, State: StatePending}}
	wrapped := WrapWikiService(&wikiStub{}, c, ownerStub{kb: &types.KnowledgeBase{ID: "shared", TenantID: 42}})
	checker := wrapped.(interface {
		CheckWikiWrite(context.Context, string) error
	})
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))
	require.ErrorContains(t, checker.CheckWikiWrite(ctx, "shared"), ErrorCodeReleaseManaged)
	require.Equal(t, uint64(42), c.tenant)
	require.Equal(t, "shared", c.kb)
	c.role = Role{Kind: KindNone, State: StateUnmanaged}
	require.NoError(t, checker.CheckWikiWrite(ctx, "shared"))
	require.ErrorContains(t, checker.CheckWikiWrite(context.Background(), "shared"), ErrorCodeClassificationUnavailable)
}

func TestWikiServiceGuardFailsClosedForMissingOwnerOrClassifier(t *testing.T) {
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))
	for _, tc := range []struct {
		name       string
		classifier Classifier
		lookup     KnowledgeBaseLookup
	}{
		{"classifier absent", nil, ownerStub{kb: &types.KnowledgeBase{ID: "kb", TenantID: 42}}},
		{"lookup absent", &classifierStub{}, nil},
		{"lookup failed", &classifierStub{}, ownerStub{err: errors.New("private details")}},
		{"kb absent", &classifierStub{}, ownerStub{}},
		{"wrong kb", &classifierStub{}, ownerStub{kb: &types.KnowledgeBase{ID: "different", TenantID: 42}}},
		{"tenant missing", &classifierStub{}, ownerStub{kb: &types.KnowledgeBase{ID: "kb"}}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			wrapped := WrapWikiService(&wikiStub{}, tc.classifier, tc.lookup)
			checker := wrapped.(interface {
				CheckWikiWrite(context.Context, string) error
			})
			require.ErrorContains(t, checker.CheckWikiWrite(ctx, "kb"), ErrorCodeClassificationUnavailable)
		})
	}
}
