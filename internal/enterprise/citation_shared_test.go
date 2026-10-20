package enterprise_test

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/mcptools"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestSharedCitationReadsAndReverifiesTheCapturedEvidence(t *testing.T) {
	world := newCitationWorld(t)
	service := release.NewService(world.store, nil, nil, release.WithPublisher(world.store))
	principal := release.Principal{TenantID: 7, Subject: "mcp_endpoint:7:reader"}
	view, err := enterprise.ReadCitation(context.Background(), service, source.NewService(world.pages),
		principal, "demo", "release-1", "1828/waiting_period", 0)
	require.NoError(t, err)
	require.Equal(t, "release-1", view.Evidence.ReleaseID)
	require.Equal(t, "保险条款.pdf", view.Span.Document)
	require.Equal(t, "等待期为90日。", view.Span.Quote)
	require.Equal(t, source.Scope{TenantID: 7, SpaceID: "demo"}, world.pages.scope)

	_, err = enterprise.ReadCitation(context.Background(), service, source.NewService(world.pages),
		principal, "demo", "release-1", "1828/waiting_period", 1)
	var mismatch *release.Error
	require.ErrorAs(t, err, &mismatch)
	require.Equal(t, release.ErrorEvidenceMismatch, mismatch.Code)
}

func citationEndpointContext() context.Context {
	ep := &types.MCPEndpoint{
		ID: "citation", TenantID: 7, Enabled: true,
		Tools: types.StringArray{types.MCPEndpointToolKnowledgeReadCitation},
	}
	ctx := context.WithValue(context.Background(), types.MCPEndpointContextKey, ep)
	ctx = context.WithValue(ctx, types.TenantIDContextKey, uint64(7))
	ctx = context.WithValue(ctx, types.UserIDContextKey, "mcp-citation")
	ctx = context.WithValue(ctx, types.TenantRoleContextKey, types.TenantRoleViewer)
	ctx = types.WithPrincipal(ctx, types.MCPEndpointPrincipal(7, ep.ID))
	ctx = types.WithCaller(ctx, types.Caller{TenantID: 7, UserID: "mcp-citation", Role: types.TenantRoleViewer})
	return types.WithTenantAPIKeyScope(ctx, types.MCPEndpointScope(ep))
}

func TestMCPCitationReusesVerifiedSourceAndSpaceVisibility(t *testing.T) {
	world := sessionWorld(t)
	service := release.NewService(world.store, nil, nil, release.WithPublisher(world.store))
	citations := mcptools.NewCitations(service, source.NewService(world.pages))
	ctx := citationEndpointContext()
	view, err := citations.Citation(ctx, 7, "demo", "release-1", "1828/waiting_period", 0)
	require.NoError(t, err)
	require.Equal(t, mcptools.Citation{Document: "保险条款.pdf", Page: 1, Quote: "等待期为90日。"}, view)
	require.Equal(t, 1, world.pages.calls)

	_, err = citations.Citation(ctx, 7, "demo", "release-1", "restricted/rule", 0)
	var hidden *release.Error
	require.ErrorAs(t, err, &hidden)
	require.Equal(t, release.ErrorMemberNotFound, hidden.Code)
	require.Equal(t, 1, world.pages.calls, "restricted member must not open its source")

	_, err = citations.Citation(ctx, 8, "demo", "release-1", "1828/waiting_period", 0)
	require.ErrorAs(t, err, &hidden)
	require.Equal(t, release.ErrorReleaseAccessDenied, hidden.Code)
	require.Equal(t, 1, world.pages.calls)
}

func TestMCPCitationVerifiesBothFingerprintsAndQuote(t *testing.T) {
	for _, mismatch := range []string{"captured fingerprint", "evidence fingerprint", "quote"} {
		world := newCitationWorld(t)
		index := 0
		switch mismatch {
		case "captured fingerprint":
			world.pages.artifact.FileSHA256 = digestOf([]byte("replacement"))
		case "evidence fingerprint":
			value := world.store.releases["release-1"]
			var payload map[string]any
			require.NoError(t, json.Unmarshal(value.Members[0].Payload, &payload))
			payload["evidence"].([]any)[0].(map[string]any)["file_sha256"] = digestOf([]byte("replacement"))
			raw, err := json.Marshal(payload)
			require.NoError(t, err)
			value.Members[0].Payload = raw
			world.store.releases["release-1"] = value
		case "quote":
			index = 1
		}
		service := release.NewService(world.store, nil, nil, release.WithPublisher(world.store))
		_, err := mcptools.NewCitations(service, source.NewService(world.pages)).
			Citation(citationEndpointContext(), 7, "demo", "release-1", "1828/waiting_period", index)
		var failure *release.Error
		require.ErrorAs(t, err, &failure, mismatch)
		require.Equal(t, release.ErrorEvidenceMismatch, failure.Code, mismatch)
	}
}

func TestSharedCitationPreservesSourceFailureClassification(t *testing.T) {
	for _, pages := range []*source.Service{
		nil, source.NewService(source.ArtifactStoreFunc(func(context.Context, source.Scope, string, int64) (
			*source.Artifact, error,
		) {
			return nil, errors.New("unavailable storage")
		})),
	} {
		world := newCitationWorld(t)
		service := release.NewService(world.store, nil, nil, release.WithPublisher(world.store))
		_, err := enterprise.ReadCitation(context.Background(), service, pages,
			release.Principal{TenantID: 7, Subject: "reader"}, "demo", "release-1", "1828/waiting_period", 0)
		var unavailable *source.Error
		require.ErrorAs(t, err, &unavailable)
		require.Equal(t, source.ErrorUnavailable, unavailable.Code)
	}
}

func TestProductionMCPCitationWithoutCaptureServiceFailsClosed(t *testing.T) {
	world := newCitationWorld(t)
	service := release.NewService(world.store, nil, nil, release.WithPublisher(world.store))
	spaces, err := releasestore.ParseSpaces(
		`[{"tenant_id":7,"space_id":"demo","raw_kb_id":"raw","wiki_kb_id":"wiki"}]`)
	require.NoError(t, err)
	deps := releasestore.NewMCPDeps(nil, spaces, nil, service, nil, nil, nil, nil, nil)
	_, err = deps.Citations.Citation(citationEndpointContext(), 7, "demo",
		"release-1", "1828/waiting_period", 0)
	var unavailable *source.Error
	require.ErrorAs(t, err, &unavailable)
	require.Equal(t, source.ErrorUnavailable, unavailable.Code)
	require.Zero(t, world.pages.calls, "missing capture service must not fall back to another page source")
}

type citationFailurePublisher struct {
	release.Publisher
	err error
}

func (p citationFailurePublisher) ReleaseByID(context.Context, uint64, string, string) (release.Release, error) {
	return release.Release{}, p.err
}

func TestCitationHTTPErrorMappingPreservesReleaseAndSourceStages(t *testing.T) {
	path := spacePath + "/releases/release-1/citation?member=1828%2Fwaiting_period&evidence=0"
	for _, err := range []error{
		errors.New("storage failed"),
		&source.Error{Code: source.ErrorUnavailable, Detail: "a source-shaped release storage failure"},
	} {
		world := newCitationWorld(t)
		service := release.NewService(world.store, nil, nil,
			release.WithPublisher(citationFailurePublisher{err: err}))
		response := get(mountRouter(service, machineKey()), path)
		require.Equal(t, http.StatusInternalServerError, response.Code)
		require.Equal(t, "INTERNAL_ERROR", code(t, response.Body.Bytes()))
	}
	world := newCitationWorld(t)
	world.pages.err = errors.New("source storage failed")
	response := get(world.router(t, machineKey()), citation("1828/waiting_period", "0"))
	require.Equal(t, http.StatusServiceUnavailable, response.Code)
	require.Equal(t, source.ErrorUnavailable, code(t, response.Body.Bytes()))

	service := release.NewService(world.store, nil, nil, release.WithPublisher(world.store))
	response = get(mountRouter(service, machineKey()), path)
	require.Equal(t, http.StatusServiceUnavailable, response.Code, "missing source service remains unavailable")
}
