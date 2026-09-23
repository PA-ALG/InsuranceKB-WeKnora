package service

import (
	"context"
	"crypto/ed25519"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type nativeDiscoverySources struct {
	source *G3PlatformSignedSourceSnapshotV1
	err    error
	calls  int
}

func (s *nativeDiscoverySources) Capture(context.Context, types.WikiReleaseScope, string, int64) (*G3PlatformSignedSourceSnapshotV1, error) {
	s.calls++
	return s.source, s.err
}
func nativeDiscoveryFixture() (*G3NativeDiscoveryService, *nativeDiscoverySources, G3NativeDiscoveryRequest, types.WikiReleaseScope) {
	scope := types.WikiReleaseScope{TenantID: 42, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki"}
	sources := &nativeDiscoverySources{source: &G3PlatformSignedSourceSnapshotV1{Snapshot: G3PlatformSourceSnapshotV1{
		Scope: scope, SnapshotSHA256: strings.Repeat("a", 64),
		Receipt: types.RegisteredSourceReceipt830G3{KnowledgeID: "doc", ParseAttempt: 1},
		Chunks:  []G3PlatformSourceChunkV1{{ID: "block-a", Index: 0, Content: "说明书各项内容以保险条款为准。"}, {ID: "block-b", Index: 1, Content: "等待期为30日。"}},
	}}}
	request := G3NativeDiscoveryRequest{Contract: G3NativeDiscoveryRequestContract, SourceSnapshotSHA256: strings.Repeat("a", 64), Phase: "plan", Language: "Chinese", Granularity: "standard", Purpose: "帮助理解保险材料"}
	request.MaxPromptBytes = 100000
	signer := &g3PlatformSnapshotSignerStub{keyID: "test", signature: []byte("signature")}
	return NewG3NativeDiscoveryService(sources, signer), sources, request, scope
}

const nativeDiscoveryRaw = `{"entities":[],"concepts":[{"name":"说明书适用顺序","slug":"concept/authority","aliases":[],"description":"说明书与条款","details":""},{"name":"未支持","slug":"concept/uncited","aliases":[],"description":"未支持提案","details":"不得成为原文"}]}`

func TestNativeDiscoveryPlanPreservesEveryChunkAndUsesNativePrompts(t *testing.T) {
	svc, source, request, scope := nativeDiscoveryFixture()
	source.source.Snapshot.Chunks[1].Content = strings.Repeat("长", 13000)
	result, err := svc.Process(context.Background(), scope, "doc", 1, request)
	require.NoError(t, err)
	require.Len(t, result.Snapshot.Windows, 2)
	require.Equal(t, []string{"block-a"}, result.Snapshot.Windows[0].ChunkIDs)
	require.Equal(t, []string{"block-b"}, result.Snapshot.Windows[1].ChunkIDs)
	require.Contains(t, result.Snapshot.Windows[1].Prompt, strings.Repeat("长", 13000))
	require.Contains(t, result.Snapshot.Windows[0].Prompt, "lightweight candidate set")
	require.Contains(t, result.Snapshot.Windows[0].Prompt, request.Purpose)
	require.Equal(t, "weknora."+G3NativeDiscoveryPlanContract, result.Authority.Domain)
	require.NotEmpty(t, result.Snapshot.SnapshotSHA256)
	require.NotEmpty(t, result.Snapshot.RequestSHA256)
}

func TestNativeDiscoveryOversizePlanFailsWithoutTruncation(t *testing.T) {
	svc, _, request, scope := nativeDiscoveryFixture()
	request.MaxPromptBytes = 100
	_, err := svc.Process(context.Background(), scope, "doc", 1, request)
	require.ErrorIs(t, err, ErrG3NativeDiscoveryInvalid)
}

func TestNativeDiscoverySnapshotResolvesNativeHandlesWithoutPublishing(t *testing.T) {
	svc, _, request, scope := nativeDiscoveryFixture()
	request.Phase, request.DiscoveryRaw = "cite", nativeDiscoveryRaw
	plan, err := svc.Process(context.Background(), scope, "doc", 1, request)
	require.NoError(t, err)
	require.Contains(t, plan.Snapshot.Windows[0].Prompt, `id="c000"`)
	require.Contains(t, plan.Snapshot.Windows[0].Prompt, "concept/authority")
	request.Phase = "snapshot"
	request.CitationRaw = `{"citations":{"concept/authority":["c000"]},"new_slugs":[{"type":"concept","name":"等待期","slug":"concept/wait","aliases":[],"description":"字段候选仍待Harness裁决","details":"","source_chunks":["c001"]}]}`
	result, err := svc.Process(context.Background(), scope, "doc", 1, request)
	require.NoError(t, err)
	require.Len(t, result.Snapshot.Candidates, 3)
	require.Equal(t, []string{"block-a"}, result.Snapshot.Candidates[0].SourceChunks)
	require.True(t, result.Snapshot.Candidates[0].HasSourceChunks)
	require.False(t, result.Snapshot.Candidates[1].HasSourceChunks)
	require.Equal(t, "MODEL_GENERATED", result.Snapshot.Candidates[1].ContentOrigin)
	require.Equal(t, "不得成为原文", result.Snapshot.Candidates[1].Details)
	require.Equal(t, []string{"block-b"}, result.Snapshot.Candidates[2].SourceChunks)
	require.NotEmpty(t, result.Snapshot.DiscoveryRawSHA256)
	require.NotEmpty(t, result.Snapshot.CitationRawSHA256)
	require.NotEmpty(t, result.Snapshot.PolicySHA256)
	// Empty citations are an observed unsupported proposal, not fabricated evidence.
	raw, err := json.Marshal(result)
	require.NoError(t, err)
	require.NotContains(t, string(raw), "active_release")
}

func TestNativeDiscoveryCrossLanguageVector(t *testing.T) {
	svc, source, request, scope := nativeDiscoveryFixture()
	signer, err := NewEd25519G3PlatformSnapshotSigner("fixture", ed25519.NewKeyFromSeed(make([]byte, 32)))
	require.NoError(t, err)
	svc.signer = signer
	requests := []G3NativeDiscoveryRequest{}
	envelopes := []*G3SignedNativeDiscoverySnapshot{}
	for _, phase := range []string{"plan", "cite", "snapshot"} {
		request.Phase = phase
		if phase != "plan" {
			request.DiscoveryRaw = nativeDiscoveryRaw
		}
		if phase == "snapshot" {
			request.CitationRaw = `{"citations":{"concept/authority":["c000"]},"new_slugs":[]}`
		}
		result, err := svc.Process(context.Background(), scope, "doc", 1, request)
		require.NoError(t, err)
		requests = append(requests, request)
		envelopes = append(envelopes, result)
	}
	raw, err := json.MarshalIndent(map[string]any{"requests": requests, "envelopes": envelopes, "source": source.source.Snapshot}, "", "  ")
	require.NoError(t, err)
	path := "testdata/g3_native_discovery_v1.json"
	if os.Getenv("UPDATE_NATIVE_DISCOVERY_FIXTURE") == "1" {
		require.NoError(t, os.WriteFile(path, raw, 0600))
	}
	want, err := os.ReadFile(path)
	require.NoError(t, err)
	require.JSONEq(t, string(want), string(raw))
}

func TestNativeDiscoveryRejectsDriftAndInvalidModelBindings(t *testing.T) {
	for name, mutate := range map[string]func(*G3NativeDiscoveryRequest){
		"source drift":     func(r *G3NativeDiscoveryRequest) { r.SourceSnapshotSHA256 = strings.Repeat("b", 64) },
		"unknown contract": func(r *G3NativeDiscoveryRequest) { r.Contract = "unknown" },
		"missing window":   func(r *G3NativeDiscoveryRequest) { r.WindowID = 3 },
		"duplicate slug": func(r *G3NativeDiscoveryRequest) {
			r.DiscoveryRaw = strings.Replace(nativeDiscoveryRaw, "concept/uncited", "concept/authority", 1)
		},
		"wrong type": func(r *G3NativeDiscoveryRequest) {
			r.DiscoveryRaw = strings.Replace(nativeDiscoveryRaw, "concept/authority", "entity/authority", 1)
		},
		"missing arrays":     func(r *G3NativeDiscoveryRequest) { r.DiscoveryRaw = `{}` },
		"duplicate property": func(r *G3NativeDiscoveryRequest) { r.DiscoveryRaw = `{"entities":[],"concepts":[],"concepts":[]}` },
		"unknown handle": func(r *G3NativeDiscoveryRequest) {
			r.CitationRaw = `{"citations":{"concept/authority":["c999"]},"new_slugs":[]}`
		},
		"unknown slug": func(r *G3NativeDiscoveryRequest) {
			r.CitationRaw = `{"citations":{"concept/unknown":["c000"]},"new_slugs":[]}`
		},
		"no citation response": func(r *G3NativeDiscoveryRequest) { r.CitationRaw = "" },
	} {
		t.Run(name, func(t *testing.T) {
			svc, _, request, scope := nativeDiscoveryFixture()
			request.Phase, request.DiscoveryRaw = "snapshot", nativeDiscoveryRaw
			request.CitationRaw = `{"citations":{"concept/authority":["c000"]},"new_slugs":[]}`
			mutate(&request)
			_, err := svc.Process(context.Background(), scope, "doc", 1, request)
			require.Error(t, err)
		})
	}
}
