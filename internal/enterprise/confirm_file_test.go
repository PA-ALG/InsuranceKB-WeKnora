package enterprise_test

// S5b-3d-2 acceptance (protected, written by Claude): a confirmation item may carry a generic
// platform source reference, and an administrator opens that exact original file from the
// confirmations page (Spec docs/design/slices/S5b-3d-2-待确认材料打开原文件.md §2).

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

var (
	materialPDF  = []byte("%PDF-1.7\n1 0 obj << >> endobj\n%%EOF\n")
	materialName = "甲 产品条款.pdf"
)

func sha(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func materialRef(raw []byte) string { return "source:v1:k-raw-1:2:" + sha(raw) }

// rawFiles stands in for the Space's RAW KB and records every file it opens.
type rawFiles struct {
	mu    sync.Mutex
	files map[string][]byte
	err   error
	opens []string
}

func (f *rawFiles) open(_ context.Context, scope source.Scope, knowledgeID string) (io.ReadCloser, string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.opens = append(f.opens, fmt.Sprintf("%d/%s/%s", scope.TenantID, scope.SpaceID, knowledgeID))
	if f.err != nil {
		return nil, "", f.err
	}
	raw, ok := f.files[knowledgeID]
	if !ok {
		return nil, "", source.ErrNotFound
	}
	return io.NopCloser(bytes.NewReader(raw)), materialName, nil
}

type fileWorld struct {
	*httpConfirmWorld
	raw *rawFiles
}

func newFileWorld() *fileWorld {
	w := newHTTPConfirmWorld()
	w.spaces = spaceDirectory{7: {"demo", "other"}}
	return &fileWorld{httpConfirmWorld: w, raw: &rawFiles{files: map[string][]byte{"k-raw-1": materialPDF}}}
}

// browserRouter mounts the session routes for one browser identity and tenant role.
func (w *fileWorld) browserRouter(who identity, role types.TenantRole, files enterprise.SourceFiles) *gin.Engine {
	r := gin.New()
	r.Use(func(c *gin.Context) {
		ctx := context.WithValue(c.Request.Context(), types.TenantIDContextKey, who.tenant)
		ctx = types.WithPrincipal(ctx, who.principal)
		ctx = types.WithCaller(ctx, types.Caller{TenantID: who.tenant, UserID: "user-1", Role: role})
		if who.apiKey {
			ctx = types.WithTenantAPIKeyScope(ctx, types.TenantAPIKeyScope{KeyID: 3, FullAccess: true})
		}
		c.Request = c.Request.WithContext(ctx)
		c.Set(types.TenantIDContextKey.String(), who.tenant)
		c.Set(types.PrincipalContextKey.String(), who.principal)
		c.Next()
	})
	group := r.Group("/api/v1/enterprise")
	deps := enterprise.SessionDeps{Confirmations: w.service, Spaces: w.spaces, Files: files}
	enterprise.MountSessionReads(group, deps)
	enterprise.MountSessionConfirmations(group, deps)
	return r
}

func (w *fileWorld) admin() *gin.Engine {
	return w.browserRouter(browser, types.TenantRoleAdmin, w.raw.open)
}

func itemJSON(subject, ref string) string {
	item := map[string]any{
		"subject": subject, "revision": "1:abc", "title": "材料 甲", "detail": "说明",
		"options": []map[string]string{{"key": "assign:p-1", "label": "归入 甲"}, {"key": "ignore", "label": "忽略"}},
	}
	if ref != "" {
		item["source_ref"] = ref
	}
	raw, _ := json.Marshal(item)
	return string(raw)
}

// submit stores items through the service-key route and returns them as JSON objects.
func (w *fileWorld) submit(t *testing.T, space string, items ...string) []map[string]any {
	t.Helper()
	body := []byte(`{"items":[` + strings.Join(items, ",") + `]}`)
	res := request(w.apiRouter(machineKey()), http.MethodPost, "/api/v1/enterprise/spaces/"+space+"/confirmations",
		"test-key", body)
	require.Equal(t, http.StatusCreated, res.Code, res.Body.String())
	var out []map[string]any
	for _, item := range data(t, res.Body.Bytes())["items"].([]any) {
		out = append(out, item.(map[string]any))
	}
	return out
}

func confirmFilePath(space, id string) string {
	return "/api/v1/enterprise/spaces/" + space + "/view/confirmations/" + id + "/file"
}

func fetch(r http.Handler, path string, header ...string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, path, nil)
	for i := 0; i+1 < len(header); i += 2 {
		req.Header.Set(header[i], header[i+1])
	}
	res := httptest.NewRecorder()
	r.ServeHTTP(res, req)
	return res
}

// oldDigest is the content digest before S5b-3d-2: canonical JSON of detail, options, title.
func oldDigest(t *testing.T) string {
	t.Helper()
	raw, err := json.Marshal(struct {
		Detail  string           `json:"detail"`
		Options []confirm.Option `json:"options"`
		Title   string           `json:"title"`
	}{"说明", []confirm.Option{{Key: "assign:p-1", Label: "归入 甲"}, {Key: "ignore", Label: "忽略"}}, "材料 甲"})
	require.NoError(t, err)
	return sha(raw)
}

func TestConfirmationSourceRefIsStoredAndOldItemsKeepTheirDigest(t *testing.T) {
	w := newFileWorld()
	items := w.submit(t, "demo", itemJSON("k-1", ""), itemJSON("k-1", materialRef(materialPDF)))
	require.Len(t, items, 2, "the same question with a source is new content")
	plain, sourced := items[0], items[1]
	require.NotEqual(t, plain["id"], sourced["id"])
	_, present := plain["source_ref"]
	require.False(t, present, "an item without a source omits the field")
	require.Equal(t, oldDigest(t), plain["content_digest"], "items without a source keep their identity")
	require.Equal(t, materialRef(materialPDF), sourced["source_ref"])
	require.NotEqual(t, plain["content_digest"], sourced["content_digest"])

	res := fetch(w.admin(), "/api/v1/enterprise/spaces/demo/view/confirmations?status=open")
	require.Equal(t, http.StatusOK, res.Code, res.Body.String())
	listed := data(t, res.Body.Bytes())["items"].([]any)
	require.Len(t, listed, 2)
	require.Equal(t, materialRef(materialPDF), listed[1].(map[string]any)["source_ref"])
}

func TestConfirmationSourceRefMustBeAPlatformReference(t *testing.T) {
	hexLower := sha(materialPDF)
	for name, value := range map[string]any{
		"Harness subject":    "material:k-raw-1",
		"zero attempt":       "source:v1:k-raw-1:0:" + hexLower,
		"upper-case hex":     "source:v1:k-raw-1:2:" + strings.ToUpper(hexLower),
		"short fingerprint":  "source:v1:k-raw-1:2:" + hexLower[:63],
		"leading space":      " source:v1:k-raw-1:2:" + hexLower,
		"trailing newline":   "source:v1:k-raw-1:2:" + hexLower + "\n",
		"other scheme":       "source:v2:k-raw-1:2:" + hexLower,
		"not a string":       7,
		"knowledge too long": "source:v1:" + strings.Repeat("k", 65) + ":2:" + hexLower,
	} {
		t.Run(name, func(t *testing.T) {
			w := newFileWorld()
			raw, _ := json.Marshal(value)
			item := strings.Replace(itemJSON("k-1", "x"), `"source_ref":"x"`, `"source_ref":`+string(raw), 1)
			body := []byte(`{"items":[` + itemJSON("k-0", "") + "," + item + `]}`)
			res := request(w.apiRouter(machineKey()), http.MethodPost, spotPath+"/confirmations", "test-key", body)
			require.Equal(t, http.StatusBadRequest, res.Code, res.Body.String())
			require.Equal(t, confirm.ErrorConfirmationInvalid, code(t, res.Body.Bytes()))
			require.Empty(t, w.store.items, "a refused batch writes nothing")
		})
	}
}

func TestAnAdministratorOpensTheExactOriginalFile(t *testing.T) {
	w := newFileWorld()
	item := w.submit(t, "demo", itemJSON("k-1", materialRef(materialPDF)))[0]
	res := fetch(w.admin(), confirmFilePath("demo", item["id"].(string)))
	require.Equal(t, http.StatusOK, res.Code, res.Body.String())
	require.Equal(t, materialPDF, res.Body.Bytes())
	require.Equal(t, "application/pdf", res.Header().Get("Content-Type"))
	require.Equal(t, "inline; filename*=UTF-8''"+url.PathEscape(materialName), res.Header().Get("Content-Disposition"))
	require.Equal(t, `"`+sha(materialPDF)+`"`, res.Header().Get("ETag"))
	require.Equal(t, "private, no-cache", res.Header().Get("Cache-Control"))
	require.Equal(t, []string{"7/demo/k-raw-1"}, w.raw.opens, "only the item's file, in the request Space")
}

func TestAConfirmationFileRevalidatesWithoutOpeningIt(t *testing.T) {
	w := newFileWorld()
	item := w.submit(t, "demo", itemJSON("k-1", materialRef(materialPDF)))[0]
	path := confirmFilePath("demo", item["id"].(string))
	res := fetch(w.admin(), path, "If-None-Match", `"`+sha(materialPDF)+`"`)
	require.Equal(t, http.StatusNotModified, res.Code)
	require.Empty(t, res.Body.Bytes())
	require.Empty(t, w.raw.opens, "a current copy needs no file read")
	other := fetch(w.admin(), path, "If-None-Match", `"`+strings.Repeat("0", 64)+`"`)
	require.Equal(t, http.StatusOK, other.Code)
	require.Len(t, w.raw.opens, 1)
}

func TestANonPDFFileDownloadsAsAnAttachment(t *testing.T) {
	w := newFileWorld()
	word := []byte("PK\x03\x04 not a pdf")
	w.raw.files["k-raw-1"] = word
	item := w.submit(t, "demo", itemJSON("k-1", materialRef(word)))[0]
	res := fetch(w.admin(), confirmFilePath("demo", item["id"].(string)))
	require.Equal(t, http.StatusOK, res.Code, res.Body.String())
	require.Equal(t, word, res.Body.Bytes())
	require.Equal(t, "application/octet-stream", res.Header().Get("Content-Type"))
	require.True(t, strings.HasPrefix(res.Header().Get("Content-Disposition"), "attachment; "))
}

func TestConfirmationFileFailuresAreTyped(t *testing.T) {
	type outcome struct {
		status int
		code   string
	}
	cases := map[string]struct {
		setup func(t *testing.T, w *fileWorld) (path string, files enterprise.SourceFiles)
		want  outcome
	}{
		"item without a source": {func(t *testing.T, w *fileWorld) (string, enterprise.SourceFiles) {
			return confirmFilePath("demo", w.submit(t, "demo", itemJSON("k-1", ""))[0]["id"].(string)), w.raw.open
		}, outcome{http.StatusNotFound, source.ErrorSourceNotFound}},
		"unknown item": {func(t *testing.T, w *fileWorld) (string, enterprise.SourceFiles) {
			return confirmFilePath("demo", "c-999"), w.raw.open
		}, outcome{http.StatusNotFound, confirm.ErrorConfirmationNotFound}},
		"item of another Space": {func(t *testing.T, w *fileWorld) (string, enterprise.SourceFiles) {
			id := w.submit(t, "other", itemJSON("k-1", materialRef(materialPDF)))[0]["id"].(string)
			return confirmFilePath("demo", id), w.raw.open
		}, outcome{http.StatusNotFound, confirm.ErrorConfirmationNotFound}},
		"file gone from the RAW KB": {func(t *testing.T, w *fileWorld) (string, enterprise.SourceFiles) {
			delete(w.raw.files, "k-raw-1")
			return confirmFilePath("demo", w.submit(t, "demo", itemJSON("k-1", materialRef(materialPDF)))[0]["id"].(string)),
				w.raw.open
		}, outcome{http.StatusNotFound, source.ErrorSourceNotFound}},
		"file changed since the question": {func(t *testing.T, w *fileWorld) (string, enterprise.SourceFiles) {
			w.raw.files["k-raw-1"] = append([]byte(nil), append(materialPDF, ' ')...)
			return confirmFilePath("demo", w.submit(t, "demo", itemJSON("k-1", materialRef(materialPDF)))[0]["id"].(string)),
				w.raw.open
		}, outcome{http.StatusConflict, "SOURCE_INTEGRITY"}},
		"no file reader configured": {func(t *testing.T, w *fileWorld) (string, enterprise.SourceFiles) {
			return confirmFilePath("demo", w.submit(t, "demo", itemJSON("k-1", materialRef(materialPDF)))[0]["id"].(string)), nil
		}, outcome{http.StatusServiceUnavailable, source.ErrorUnavailable}},
		"storage failure": {func(t *testing.T, w *fileWorld) (string, enterprise.SourceFiles) {
			w.raw.err = errors.New("object store down")
			return confirmFilePath("demo", w.submit(t, "demo", itemJSON("k-1", materialRef(materialPDF)))[0]["id"].(string)),
				w.raw.open
		}, outcome{http.StatusServiceUnavailable, source.ErrorUnavailable}},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			w := newFileWorld()
			path, files := tc.setup(t, w)
			res := fetch(w.browserRouter(browser, types.TenantRoleAdmin, files), path)
			require.Equal(t, tc.want.status, res.Code, res.Body.String())
			require.Equal(t, tc.want.code, code(t, res.Body.Bytes()))
			require.NotContains(t, res.Body.String(), "%PDF")
		})
	}
}

func TestAClosedItemStillOpensItsFile(t *testing.T) {
	w := newFileWorld()
	id := w.submit(t, "demo", itemJSON("k-1", materialRef(materialPDF)))[0]["id"].(string)
	closed := request(w.apiRouter(machineKey()), http.MethodPost, spotPath+"/confirmations/"+id+"/closure",
		"test-key", []byte(`{"reason":"obsolete"}`))
	require.Equal(t, http.StatusCreated, closed.Code, closed.Body.String())
	res := fetch(w.admin(), confirmFilePath("demo", id))
	require.Equal(t, http.StatusOK, res.Code, res.Body.String())
	require.Equal(t, materialPDF, res.Body.Bytes())
}

func TestTheFileNeedsAnAdministratorBrowserSession(t *testing.T) {
	w := newFileWorld()
	id := w.submit(t, "demo", itemJSON("k-1", materialRef(materialPDF)))[0]["id"].(string)
	serviceKey := identity{tenant: 7, principal: browser.principal, apiKey: true}
	otherTenant := identity{tenant: 8, principal: browser.principal}
	for name, probe := range map[string]struct {
		who    identity
		role   types.TenantRole
		status int
		code   string
	}{
		"contributor":     {browser, types.TenantRoleContributor, http.StatusForbidden, release.ErrorReleaseAccessDenied},
		"viewer":          {browser, types.TenantRoleViewer, http.StatusForbidden, release.ErrorReleaseAccessDenied},
		"service key":     {serviceKey, types.TenantRoleOwner, http.StatusForbidden, release.ErrorReleaseAccessDenied},
		"tenant 8 caller": {otherTenant, types.TenantRoleOwner, http.StatusNotFound, release.ErrorReleaseNotFound},
	} {
		t.Run(name, func(t *testing.T) {
			res := fetch(w.browserRouter(probe.who, probe.role, w.raw.open), confirmFilePath("demo", id))
			require.Equal(t, probe.status, res.Code, res.Body.String())
			require.Equal(t, probe.code, code(t, res.Body.Bytes()))
		})
	}
	machine := request(w.apiRouter(machineKey()), http.MethodGet, confirmFilePath("demo", id), "test-key", nil)
	require.NotEqual(t, http.StatusOK, machine.Code, "the service key has no file route")
	require.Empty(t, w.raw.opens, "a refused request opens no file")
}
