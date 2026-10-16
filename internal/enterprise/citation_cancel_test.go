package enterprise_test

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/middleware"
)

// slowFile hands out one byte on the first Read. Later reads end the file, or, when block is
// set, wait until Close (a slow source).
type slowFile struct {
	mu       sync.Mutex
	reads    int
	block    bool
	closed   chan struct{}
	afterOne func() // called during the first Read
	blocking chan struct{}
}

func newSlowFile(block bool) *slowFile {
	return &slowFile{block: block, closed: make(chan struct{}), blocking: make(chan struct{})}
}

func (f *slowFile) Read(p []byte) (int, error) {
	f.mu.Lock()
	f.reads++
	n := f.reads
	f.mu.Unlock()
	if n == 1 {
		if f.afterOne != nil {
			f.afterOne()
		}
		p[0] = '%'
		return 1, nil
	}
	if !f.block {
		return 0, io.EOF
	}
	close(f.blocking)
	<-f.closed
	return 0, os.ErrClosed
}

func (f *slowFile) Close() error {
	select {
	case <-f.closed:
	default:
		close(f.closed)
	}
	return nil
}

func (f *slowFile) readCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.reads
}

func cancelRouter(t *testing.T, world *citationWorld, file *slowFile) *gin.Engine {
	t.Helper()
	schema, err := os.ReadFile("../../contracts/candidate_bundle.schema.json")
	require.NoError(t, err)
	service := release.NewService(world.store, nil, map[string][]byte{"candidate_bundle": schema},
		release.WithPublisher(world.store))
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(middleware.Auth(tenantService{}, userService{}, nil, keyService{key: machineKey()}, nil))
	gate := middleware.NewAPIKeyRouteAuthorizer()
	api := r.Group("/api/v1", gate.Middleware())
	enterprise.Mount(api.Group("/enterprise/spaces/:space_id"), enterprise.Deps{
		Candidates: service, Sources: source.NewService(world.pages), Authorizer: gate,
		Files: func(context.Context, source.Scope, string) (io.ReadCloser, string, error) {
			return file, "保险条款.pdf", nil
		},
	})
	return r
}

func cancellableRequest(ctx context.Context) *http.Request {
	req := httptest.NewRequest(http.MethodGet, filePath, nil).WithContext(ctx)
	req.Header.Set("X-API-Key", "test-key")
	return req
}

func TestACancelledFileRequestStopsReadingAndClosesTheFile(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	file := newSlowFile(false)
	file.afterOne = cancel
	w := httptest.NewRecorder()
	cancelRouter(t, newCitationWorld(t), file).ServeHTTP(w, cancellableRequest(ctx))

	require.Equal(t, 1, file.readCount(), "no read after the request was cancelled")
	select {
	case <-file.closed:
	default:
		t.Fatal("the file must be closed")
	}
	require.NotEqual(t, http.StatusOK, w.Code)
	require.NotContains(t, w.Body.String(), "%PDF")
}

func TestCancellingEndsAReadBlockedOnASlowSource(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	file := newSlowFile(true)
	router := cancelRouter(t, newCitationWorld(t), file)
	w := httptest.NewRecorder()
	done := make(chan struct{})
	go func() {
		router.ServeHTTP(w, cancellableRequest(ctx))
		close(done)
	}()

	select {
	case <-file.blocking:
	case <-time.After(5 * time.Second):
		t.Fatal("the handler never reached the blocking read")
	}
	cancel()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("cancellation did not end the blocked read")
	}
	require.NotEqual(t, http.StatusOK, w.Code)
	require.Equal(t, 2, file.readCount())
}
