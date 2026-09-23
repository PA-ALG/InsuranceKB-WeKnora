package handler

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type nativeDiscoveryProducerStub struct {
	calls int
	scope types.WikiReleaseScope
	err   error
}

func (s *nativeDiscoveryProducerStub) Process(_ context.Context, scope types.WikiReleaseScope, _ string, _ int64, _ service.G3NativeDiscoveryRequest) (*service.G3SignedNativeDiscoverySnapshot, error) {
	s.calls++
	s.scope = scope
	return &service.G3SignedNativeDiscoverySnapshot{}, s.err
}
func TestNativeDiscoveryHandlerRetainsScopeAndRejectsMalformedRequests(t *testing.T) {
	for _, tc := range []struct {
		name, body    string
		producerError error
		status, calls int
	}{
		{"valid", `{"contract":"g3-native-discovery-request.830.v1"}`, nil, 200, 1},
		{"unknown field", `{"unknown":true}`, nil, 400, 0},
		{"duplicate key", `{"phase":"plan","phase":"snapshot"}`, nil, 400, 0},
		{"trailing value", `{} {}`, nil, 400, 0},
		{"denied source", `{}`, service.ErrG3PlatformSnapshotUnauthorized, 403, 1},
		{"stale source", `{}`, service.ErrG3PlatformSnapshotUnavailable, 409, 1},
		{"invalid proposal", `{}`, service.ErrG3NativeDiscoveryInvalid, 400, 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			producer := &nativeDiscoveryProducerStub{err: tc.producerError}
			h := NewG3PlatformSnapshotsHandler(NewWikiReleaseHandler(nil), nil, nil, nil)
			h.native = producer
			h.nativeConfig = &config.Config{ProductIngestion: &config.ProductIngestionConfig{
				Enabled: true, TenantID: 42, SpaceID: "space-1", RawKBID: "raw-1", WikiKBID: "wiki-1", WikiProducerPolicy: config.NativeCandidatesPolicy,
			}}
			engine := newG3PlatformHandlerEngine(h)
			engine.POST("/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/platform/sources/:knowledge_id/attempts/:attempt/native-discovery", h.NativeDiscovery)
			reply := httptest.NewRecorder()
			engine.ServeHTTP(reply, httptest.NewRequest(http.MethodPost, "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/platform/sources/doc/attempts/1/native-discovery", strings.NewReader(tc.body)))
			require.Equal(t, tc.status, reply.Code, reply.Body.String())
			require.Equal(t, tc.calls, producer.calls)
			if tc.calls > 0 {
				require.Equal(t, types.WikiReleaseScope{TenantID: 42, SpaceID: "space-1", RawKBID: "raw-1", WikiKBID: "wiki-1"}, producer.scope)
			}
			var body map[string]any
			require.NoError(t, json.Unmarshal(reply.Body.Bytes(), &body))
		})
	}
}

func TestNativeDiscoveryHandlerNeedsExplicitCandidateMode(t *testing.T) {
	producer := &nativeDiscoveryProducerStub{}
	h := NewG3PlatformSnapshotsHandler(NewWikiReleaseHandler(nil), nil, nil, nil)
	h.native = producer
	engine := newG3PlatformHandlerEngine(h)
	engine.POST("/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/platform/sources/:knowledge_id/attempts/:attempt/native-discovery", h.NativeDiscovery)
	reply := httptest.NewRecorder()
	engine.ServeHTTP(reply, httptest.NewRequest(http.MethodPost, "/knowledgebase/wiki-1/wiki/release-scopes/space-1/raw/raw-1/platform/sources/doc/attempts/1/native-discovery", strings.NewReader(`{}`)))
	require.Equal(t, http.StatusServiceUnavailable, reply.Code)
	require.Zero(t, producer.calls)
}
