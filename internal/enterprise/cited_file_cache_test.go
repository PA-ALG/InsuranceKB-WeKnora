package enterprise_test

// Issue #375 acceptance (protected, written by Claude): a cited original file is revalidated on
// every request. Authorization, the "this release cites it" check and (R1) the same live source
// check come first; a matching If-None-Match then answers 304 without reading the file. Nothing
// lets the browser reuse the file without asking the server (ETag + private, no-cache).

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

func conditionalRead(r http.Handler, path, tag string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, path, nil)
	if tag != "" {
		req.Header.Set("If-None-Match", tag)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func requireRevalidatedEveryTime(t *testing.T, w *httptest.ResponseRecorder) {
	t.Helper()
	require.Equal(t, `"`+pdfSHA+`"`, w.Header().Get("ETag"))
	require.Equal(t, "private, no-cache", w.Header().Get("Cache-Control"))
	require.Contains(t, w.Header().Values("Vary"), "Authorization, X-Tenant-ID")
}

func TestTheCitedFileIsRevalidatedOnEveryRequest(t *testing.T) {
	world := newCitationWorld(t)
	w := conditionalGET(world.router(t, machineKey()), filePath, "")
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	require.Equal(t, pdfBytes, w.Body.Bytes())
	requireRevalidatedEveryTime(t, w)
	require.NotContains(t, w.Header().Get("Cache-Control"), "max-age")
	require.NotContains(t, w.Header().Get("Cache-Control"), "immutable")

	stale := newCitationWorld(t)
	w = conditionalGET(stale.router(t, machineKey()), filePath, `"`+digestOf([]byte("older"))+`"`)
	require.Equal(t, http.StatusOK, w.Code, "a different validator gets the full file")
	require.Equal(t, pdfBytes, w.Body.Bytes())
	require.Len(t, stale.opens, 1)
}

func TestAMatchingValidatorAnswers304WithoutOpeningTheFile(t *testing.T) {
	for _, tag := range []string{`"` + pdfSHA + `"`, `W/"` + pdfSHA + `"`, `"x", "` + pdfSHA + `"`, "*"} {
		t.Run(tag, func(t *testing.T) {
			world := newCitationWorld(t)
			w := conditionalGET(world.router(t, machineKey()), filePath, tag)
			require.Equal(t, http.StatusNotModified, w.Code, w.Body.String())
			require.Empty(t, w.Body.Bytes())
			requireRevalidatedEveryTime(t, w)
			// R1: the 304 passes the same live source check (one open), but never reads the file.
			require.Equal(t, []source.Scope{{TenantID: 7, SpaceID: "demo"}}, world.opens)
			require.Equal(t, len(pdfBytes), world.files["k-1"].(*bytes.Reader).Len(), "a 304 never reads or hashes the file")
		})
	}
}

func TestAccessIsCheckedBeforeAMatchingValidator(t *testing.T) {
	tag := `"` + pdfSHA + `"`
	tenant := uint64(7)
	restricted := &types.TenantAPIKey{
		ID: 2, TenantID: &tenant, FullAccess: true, KnowledgeBaseIDs: types.StringArray{"raw-1"},
	}
	world := newCitationWorld(t)
	w := conditionalGET(world.router(t, restricted), filePath, tag)
	require.Equal(t, http.StatusForbidden, w.Code, w.Body.String())
	require.Empty(t, w.Header().Get("ETag"))

	anonymous := conditionalRead(world.router(t, machineKey()), filePath, tag)
	require.Equal(t, http.StatusUnauthorized, anonymous.Code)
	require.Empty(t, anonymous.Header().Get("ETag"))

	// The release cites attempt 2 of k-1 only; k-9 and release-9 do not exist.
	for _, path := range []string{
		releasePath + "/sources/k-1/attempts/3/file",
		releasePath + "/sources/k-9/attempts/2/file",
		"/api/v1/enterprise/spaces/demo/releases/release-9/sources/k-1/attempts/2/file",
	} {
		w = conditionalGET(world.router(t, machineKey()), path, tag)
		require.Equal(t, http.StatusNotFound, w.Code, path+" "+w.Body.String())
		require.Empty(t, w.Header().Get("ETag"), path)
		require.Empty(t, w.Header().Get("Cache-Control"), path)
	}
	require.Empty(t, world.opens)
}

func TestTheSessionFileRouteFollowsTheSameRule(t *testing.T) {
	world := sessionWorld(t)
	r := sessionRouter(t, world, browser)
	path := viewPath + "/release-1/sources/k-1/attempts/2/file"

	w := conditionalRead(r, path, "")
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	requireRevalidatedEveryTime(t, w)
	w = conditionalRead(r, path, `"`+pdfSHA+`"`)
	require.Equal(t, http.StatusNotModified, w.Code, w.Body.String())
	require.Len(t, world.opens, 2, "the 304 runs the same live source check as the full read")

	// k-9 is cited only by a member outside the Space scope: a validator cannot reveal it.
	w = conditionalRead(r, viewPath+"/release-1/sources/k-9/attempts/1/file", "*")
	require.Equal(t, http.StatusNotFound, w.Code, w.Body.String())
	require.Empty(t, w.Header().Get("ETag"))
	require.Len(t, world.opens, 2)
}
