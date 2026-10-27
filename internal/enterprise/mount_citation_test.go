package enterprise_test

// S4c-2b-2 acceptance (protected, written by Claude): opening a citation of an explicit release
// and the exact original file it points to (Spec docs/design/slices/S4c-2b-2-证据回验与回跳.md §3.4).
// Reuses publishStore, pageStore, request, data, code, machineKey and the auth fakes of this
// package. RED until S4c-2b-2 implements it.

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/middleware"
	"github.com/Tencent/WeKnora/internal/types"
)

var (
	pdfBytes  = []byte("%PDF-1.7 the cited terms")
	pdfSHA    = digestOf(pdfBytes)
	citingRef = "source:v1:k-1:2:" + pdfSHA
)

const (
	citedPage   = "第五条\r\n等待期为90日。"
	releasePath = "/api/v1/enterprise/spaces/demo/releases/release-1"
	filePath    = releasePath + "/sources/k-1/attempts/2/file"
)

func digestOf(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

// citedArtifact is page 1 of k-1 attempt 2: every non-space character of "等待期为90日。" has a box on one line.
func citedArtifact(t *testing.T) *source.Artifact {
	t.Helper()
	boxes := []any{}
	for i, ch := range []rune(citedPage) {
		if ch == '\r' || ch == '\n' {
			continue
		}
		x := 100_000 + i*20_000
		boxes = append(boxes, map[string]any{
			"bbox": []int{x, 200_000, x + 20_000, 220_000}, "global_codepoint_start": i, "global_codepoint_end": i + 1,
		})
	}
	native, err := json.Marshal(map[string]any{
		"contract": "pdf-native-structure-v2", "coordinate_space": "normalized_0_1e6_top_left",
		"pages": []any{map[string]any{
			"page_number": 1, "global_codepoint_start": 0, "global_codepoint_end": len([]rune(citedPage)),
			"page_text_sha256": digestOf([]byte(citedPage)), "width_points": "595.28", "height_points": "841.89",
			"bboxes": boxes,
		}},
	})
	require.NoError(t, err)
	return &source.Artifact{
		KnowledgeID: "k-1", ParseAttempt: 2, FileName: "保险条款.pdf", FileSHA256: pdfSHA,
		ParserIdentitySHA256: digestOf([]byte("pdfium")), Markdown: citedPage, NativeJSON: native,
	}
}

func evidenceJSON(kind string, start, end int, quote string) map[string]any {
	locator := map[string]any{"kind": kind, "page": 1, "start": start, "end": end}
	return map[string]any{
		"source_ref": citingRef, "file_sha256": pdfSHA, "quote": quote, "access_scope": "space", "locator": locator,
	}
}

func releaseMember(t *testing.T, slug, origin string, evidence ...map[string]any) release.Member {
	t.Helper()
	payload := map[string]any{"origin": origin, "state": "present", "value": "90日"}
	refs := []string{}
	if len(evidence) > 0 {
		payload["evidence"] = evidence
		refs = []string{citingRef}
	}
	raw, err := json.Marshal(payload)
	require.NoError(t, err)
	return release.Member{
		Kind: "claim", LogicalSlug: slug, Payload: raw, MemberDigest: digestOf(raw),
		EvidenceRefs: refs, AccessScope: "space",
	}
}

type citationWorld struct {
	store *publishStore
	pages *pageStore
	files map[string]io.Reader
	opens []source.Scope
}

func newCitationWorld(t *testing.T) *citationWorld {
	t.Helper()
	store := newPublishStore()
	store.releases["release-1"] = release.Release{ID: "release-1", Epoch: 1, Members: []release.Member{
		releaseMember(t, "1828/waiting_period", "SOURCE_SUPPORTED",
			evidenceJSON("PDF_TEXT_SPAN", 5, 13, "等待期为90日。"),
			evidenceJSON("PDF_TEXT_SPAN", 5, 13, "等待期为60日。"),
			evidenceJSON("OCR_REGION", 5, 13, "等待期为90日。")),
		releaseMember(t, "concept/waiting_period", "MODEL_GENERATED"),
	}}
	store.head = release.Head{ReleaseID: "release-1", Epoch: 1}
	return &citationWorld{
		store: store, pages: &pageStore{artifact: citedArtifact(t)},
		files: map[string]io.Reader{"k-1": bytes.NewReader(pdfBytes)},
	}
}

func (w *citationWorld) router(t *testing.T, key *types.TenantAPIKey) *gin.Engine {
	t.Helper()
	schema, err := os.ReadFile("../../contracts/candidate_bundle.schema.json")
	require.NoError(t, err)
	service := release.NewService(w.store, nil, map[string][]byte{"candidate_bundle": schema},
		release.WithPublisher(w.store))
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(middleware.Auth(tenantService{}, userService{}, nil, keyService{key: key}, nil))
	gate := middleware.NewAPIKeyRouteAuthorizer()
	api := r.Group("/api/v1", gate.Middleware())
	enterprise.Mount(api.Group("/enterprise/spaces/:space_id"), enterprise.Deps{
		Candidates: service, Sources: source.NewService(w.pages), Authorizer: gate,
		Files: func(_ context.Context, scope source.Scope, knowledgeID string) (io.ReadCloser, string, error) {
			w.opens = append(w.opens, scope)
			reader, ok := w.files[knowledgeID]
			if !ok {
				return nil, "", source.ErrNotFound
			}
			return io.NopCloser(reader), "保险条款.pdf", nil
		},
	})
	return r
}

func get(r http.Handler, path string) *httptest.ResponseRecorder {
	return request(r, http.MethodGet, path, "test-key", nil)
}

func citation(member string, index string) string {
	return releasePath + "/citation?" + url.Values{"member": {member}, "evidence": {index}}.Encode()
}

func TestACitationOpensTheVerifiedQuoteWithItsHighlight(t *testing.T) {
	world := newCitationWorld(t)
	w := get(world.router(t, machineKey()), citation("1828/waiting_period", "0"))
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	got := data(t, w.Body.Bytes())

	require.Equal(t, "release-1", got["release_id"])
	require.Equal(t, "1828/waiting_period", got["member"])
	require.Equal(t, float64(0), got["evidence_index"])
	require.Equal(t, "SOURCE_SUPPORTED", got["origin"])
	require.Equal(t, map[string]any{
		"knowledge_id": "k-1", "parse_attempt": float64(2), "document": "保险条款.pdf", "file_sha256": pdfSHA,
	}, got["source"])
	require.Equal(t, map[string]any{
		"number": float64(1), "width_points": "595.28", "height_points": "841.89",
	}, got["page"])
	require.Equal(t, float64(5), got["start"])
	require.Equal(t, float64(13), got["end"])
	require.Equal(t, "等待期为90日。", got["quote"])
	require.Equal(t, map[string]any{
		"coordinate_space": "normalized_0_1e6_top_left", "complete": true,
		"rects": []any{[]any{float64(200_000), float64(200_000), float64(360_000), float64(220_000)}},
	}, got["highlight"])
	require.Equal(t, "/api/v1/enterprise/spaces/demo/releases/release-1/sources/k-1/attempts/2/file", got["file"])
	require.Equal(t, source.Scope{TenantID: 7, SpaceID: "demo"}, world.pages.scope)
}

func TestCitationFailuresAreTyped(t *testing.T) {
	cases := []struct {
		name, path string
		status     int
		code       string
	}{
		{
			"unknown release", "/api/v1/enterprise/spaces/demo/releases/release-9/citation?member=a&evidence=0",
			http.StatusNotFound, release.ErrorReleaseNotFound,
		},
		{"unknown member", citation("1828/unknown", "0"), http.StatusNotFound, release.ErrorMemberNotFound},
		{
			"evidence index beyond", citation("1828/waiting_period", "3"), http.StatusNotFound,
			release.ErrorEvidenceNotFound,
		},
		{
			"model-generated member", citation("concept/waiting_period", "0"), http.StatusNotFound,
			release.ErrorEvidenceNotFound,
		},
		{
			"quote no longer matches", citation("1828/waiting_period", "1"), http.StatusConflict,
			release.ErrorEvidenceMismatch,
		},
		{
			"locator kind not supported", citation("1828/waiting_period", "2"), http.StatusUnprocessableEntity,
			release.ErrorEvidenceUnsupported,
		},
		{"member missing", releasePath + "/citation?evidence=0", http.StatusBadRequest, "INVALID_REQUEST"},
		{"evidence not a number", citation("1828/waiting_period", "x"), http.StatusBadRequest, "INVALID_REQUEST"},
		{"evidence negative", citation("1828/waiting_period", "-1"), http.StatusBadRequest, "INVALID_REQUEST"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			world := newCitationWorld(t)
			w := get(world.router(t, machineKey()), c.path)
			require.Equal(t, c.status, w.Code, w.Body.String())
			require.Equal(t, c.code, code(t, w.Body.Bytes()))
		})
	}

	world := newCitationWorld(t)
	world.pages.artifact, world.pages.err = nil, source.ErrNotCaptured
	w := get(world.router(t, machineKey()), citation("1828/waiting_period", "0"))
	require.Equal(t, http.StatusConflict, w.Code, w.Body.String())
	require.Equal(t, source.ErrorNotCaptured, code(t, w.Body.Bytes()))
}

func TestTheCitedFileIsServedOnlyWhenItIsTheExactFingerprint(t *testing.T) {
	world := newCitationWorld(t)
	w := get(world.router(t, machineKey()), filePath)
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	require.Equal(t, pdfBytes, w.Body.Bytes())
	require.Equal(t, "application/pdf", w.Header().Get("Content-Type"))
	require.Equal(t, `"`+pdfSHA+`"`, w.Header().Get("ETag"))
	require.Equal(t, "private, no-cache", w.Header().Get("Cache-Control"))
	require.Contains(t, w.Header().Get("Content-Disposition"), "inline")
	require.Contains(t, w.Header().Get("Content-Disposition"), "filename*=UTF-8''"+url.PathEscape("保险条款.pdf"))
	require.Equal(t, []source.Scope{{TenantID: 7, SpaceID: "demo"}}, world.opens)

	uncited := newCitationWorld(t)
	w = get(uncited.router(t, machineKey()), releasePath+"/sources/k-1/attempts/3/file")
	require.Equal(t, http.StatusNotFound, w.Code)
	require.Equal(t, "SOURCE_NOT_FOUND", code(t, w.Body.Bytes()))
	require.Empty(t, uncited.opens, "an attempt the release does not cite is never opened")

	replaced := newCitationWorld(t)
	replaced.files["k-1"] = bytes.NewReader([]byte("%PDF-1.7 a different file"))
	w = get(replaced.router(t, machineKey()), filePath)
	require.Equal(t, http.StatusConflict, w.Code)
	require.Equal(t, "SOURCE_INTEGRITY", code(t, w.Body.Bytes()))

	oversized := newCitationWorld(t)
	oversized.files["k-1"] = io.LimitReader(zeros{}, 256<<20+1)
	w = get(oversized.router(t, machineKey()), filePath)
	require.Equal(t, http.StatusConflict, w.Code)
	require.Equal(t, "SOURCE_INTEGRITY", code(t, w.Body.Bytes()))

	gone := newCitationWorld(t)
	delete(gone.files, "k-1")
	w = get(gone.router(t, machineKey()), filePath)
	require.Equal(t, http.StatusNotFound, w.Code)
	require.Equal(t, "SOURCE_NOT_FOUND", code(t, w.Body.Bytes()))

	for _, attempt := range []string{"0", "x"} {
		path := releasePath + "/sources/k-1/attempts/" + attempt + "/file"
		w = get(newCitationWorld(t).router(t, machineKey()), path)
		require.Equal(t, http.StatusBadRequest, w.Code, path)
		require.Equal(t, "INVALID_REQUEST", code(t, w.Body.Bytes()))
	}
}

func TestCitationRoutesRequireTheFullServiceKey(t *testing.T) {
	tenant := uint64(7)
	restricted := &types.TenantAPIKey{
		ID: 2, TenantID: &tenant, FullAccess: true, KnowledgeBaseIDs: types.StringArray{"raw-1"},
	}
	for _, path := range []string{citation("1828/waiting_period", "0"), filePath} {
		world := newCitationWorld(t)
		w := request(world.router(t, restricted), http.MethodGet, path, "test-key", nil)
		require.Equal(t, http.StatusForbidden, w.Code, path)
		w = request(world.router(t, machineKey()), http.MethodGet, path, "", nil)
		require.Equal(t, http.StatusUnauthorized, w.Code, path)
		require.Empty(t, world.opens)
		require.Zero(t, world.pages.calls)
	}
}

type zeros struct{}

func (zeros) Read(p []byte) (int, error) {
	clear(p)
	return len(p), nil
}
