package enterprise_test

import (
	"context"
	"net/http"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type mountRetirer struct{ fail error }

func (r mountRetirer) Retire(_ context.Context, w release.RetirementWrite) (release.Retirement, error) {
	return release.Retirement{
		ReleaseID: w.ReleaseID, Reason: w.Reason, Subject: w.Subject, RetiredAt: time.Unix(1, 0).UTC(),
	}, r.fail
}

func (r mountRetirer) SourcePins(context.Context, uint64, string, string) ([]release.SourcePin, error) {
	return []release.SourcePin{{ReleaseID: "r1", ParseAttempt: 2, Active: true}}, r.fail
}

func retirementService(retirer mountRetirer) *release.Service {
	store := newPublishStore()
	return release.NewService(store, nil, nil, release.WithPublisher(store), release.WithRetirer(retirer))
}

func TestMountRetirementAndSourcePins(t *testing.T) {
	router := mountRouter(retirementService(mountRetirer{}), machineKey())
	body := []byte(`{"reason":" done "}`)
	w := request(router, http.MethodPost, spacePath+"/releases/r1/retirement", "test-key", body)
	require.Equal(t, 200, w.Code, w.Body.String())
	require.Equal(t, "done", data(t, w.Body.Bytes())["reason"])
	w = request(router, http.MethodGet, spacePath+"/sources/k1/pins", "test-key", nil)
	require.Equal(t, 200, w.Code, w.Body.String())
	require.Len(t, data(t, w.Body.Bytes())["pins"], 1)
}

func TestMountRetirementErrors(t *testing.T) {
	for _, failure := range []struct {
		code   string
		status int
	}{
		{release.ErrorReleaseActive, 409},
		{release.ErrorSourceUnavailable, 409},
		{release.ErrorRetirementInvalid, 400},
		{release.ErrorInvalidRequest, 400},
		{release.ErrorReleaseNotFound, 404},
		{release.ErrorServiceUnavailable, 503},
	} {
		for _, path := range []struct{ method, path string }{
			{http.MethodPost, spacePath + "/releases/r1/retirement"},
			{http.MethodGet, spacePath + "/sources/k1/pins"},
		} {
			svc := retirementService(mountRetirer{fail: &release.Error{Code: failure.code}})
			body := []byte(`{"reason":"done"}`)
			w := request(mountRouter(svc, machineKey()), path.method, path.path, "test-key", body)
			require.Equal(t, failure.status, w.Code, w.Body.String())
			require.Equal(t, failure.code, code(t, w.Body.Bytes()))
		}
	}
}

func TestMountRetirementRoutesFailClosed(t *testing.T) {
	for _, path := range []struct{ method, path string }{
		{http.MethodPost, spacePath + "/releases/r1/retirement"},
		{http.MethodGet, spacePath + "/sources/k1/pins"},
	} {
		w := request(mountRouter(nil, machineKey()), path.method, path.path, "test-key", []byte(`{"reason":"done"}`))
		require.Equal(t, 503, w.Code)
		w = request(mountRouter(retirementService(mountRetirer{}), machineKey()), path.method, path.path, "", nil)
		require.Equal(t, 401, w.Code)
		for _, key := range []*types.TenantAPIKey{
			{ID: 1, TenantID: machineKey().TenantID, Capabilities: types.StringArray{"retrieve"}},
			{
				ID: 1, TenantID: machineKey().TenantID, FullAccess: true,
				KnowledgeBaseIDs: types.StringArray{"restricted"},
			},
		} {
			w = request(mountRouter(retirementService(mountRetirer{}), key), path.method, path.path, "test-key", nil)
			require.Equal(t, 403, w.Code, w.Body.String())
		}
	}
}
