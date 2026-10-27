package enterprise_test

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

type countedConfirmationStore struct {
	confirm.Store
	reads int
}

func (s *countedConfirmationStore) ItemByID(
	ctx context.Context, tenant uint64, space, id string,
) (confirm.Item, bool, error) {
	s.reads++
	return s.Store.ItemByID(ctx, tenant, space, id)
}

func TestConfirmationFileConditionalRequestsReauthorizeBeforeReading(t *testing.T) {
	w := newFileWorld()
	id := w.submit(t, "demo", itemJSON("opaque:document", materialRef(materialPDF)))[0]["id"].(string)
	store := &countedConfirmationStore{Store: w.store}
	w.service = confirm.NewService(store)
	etag := `"` + sha(materialPDF) + `"`
	path := confirmFilePath("demo", id)
	res := fetch(w.admin(), path, "If-None-Match", etag)
	require.Equal(t, http.StatusNotModified, res.Code)
	require.Equal(t, etag, res.Header().Get("ETag"))
	require.Equal(t, "private, no-cache", res.Header().Get("Cache-Control"))
	require.Equal(t, 1, store.reads)
	require.Empty(t, w.raw.opens)

	for _, role := range []types.TenantRole{types.TenantRoleViewer, types.TenantRoleContributor, ""} {
		res = fetch(w.browserRouter(browser, role, w.raw.open), path, "If-None-Match", etag)
		require.Equal(t, http.StatusForbidden, res.Code, res.Body.String())
		require.Equal(t, 1, store.reads, "trusted admin check must precede the item read")
	}
	// A cached file cannot survive deletion of the scoped item.
	delete(w.store.items, "7/"+id)
	res = fetch(w.admin(), path, "If-None-Match", etag)
	require.Equal(t, http.StatusNotFound, res.Code)
	require.Equal(t, confirm.ErrorConfirmationNotFound, code(t, res.Body.Bytes()))
	require.Equal(t, 2, store.reads)
	require.Empty(t, w.raw.opens)
}

func TestConfirmationFileRequiresAnExactETagAndAStoredReference(t *testing.T) {
	w := newFileWorld()
	id := w.submit(t, "demo", itemJSON("opaque:document", materialRef(materialPDF)))[0]["id"].(string)
	etag := `"` + sha(materialPDF) + `"`
	for _, header := range []string{"W/" + etag, etag + `, "other"`, "*", sha(materialPDF)} {
		res := fetch(w.admin(), confirmFilePath("demo", id), "If-None-Match", header)
		require.Equal(t, http.StatusOK, res.Code, res.Body.String())
		require.Equal(t, materialPDF, res.Body.Bytes())
	}
	require.Len(t, w.raw.opens, 4)
	item := w.store.items["7/"+id]
	item.SourceRef = "invalid stored reference"
	w.store.items["7/"+id] = item
	res := fetch(w.admin(), confirmFilePath("demo", id), "If-None-Match", etag)
	require.Equal(t, http.StatusNotFound, res.Code)
	require.Equal(t, source.ErrorSourceNotFound, code(t, res.Body.Bytes()))
	require.Len(t, w.raw.opens, 4)
}

type trackedConfirmationFile struct {
	io.ReadCloser
	closes atomic.Int32
}

func (f *trackedConfirmationFile) Close() error {
	f.closes.Add(1)
	return f.ReadCloser.Close()
}

type failedConfirmationRead struct{}

func (failedConfirmationRead) Read([]byte) (int, error) {
	return 0, errors.New("private storage detail")
}

func TestConfirmationFileClosesVerifiedAndFailedReadsExactlyOnce(t *testing.T) {
	for _, tc := range []struct {
		name   string
		reader io.Reader
		status int
	}{
		{"verified", bytes.NewReader(materialPDF), http.StatusOK},
		{"replaced", strings.NewReader("replacement secret"), http.StatusConflict},
		{"read error", failedConfirmationRead{}, http.StatusServiceUnavailable},
	} {
		t.Run(tc.name, func(t *testing.T) {
			w := newFileWorld()
			id := w.submit(t, "demo", itemJSON("document", materialRef(materialPDF)))[0]["id"].(string)
			file := &trackedConfirmationFile{ReadCloser: io.NopCloser(tc.reader)}
			files := func(context.Context, source.Scope, string) (io.ReadCloser, string, error) {
				return file, "material.pdf", nil
			}
			res := fetch(w.browserRouter(browser, types.TenantRoleAdmin, files), confirmFilePath("demo", id))
			require.Equal(t, tc.status, res.Code)
			require.EqualValues(t, 1, file.closes.Load())
			if tc.status != http.StatusOK {
				require.NotContains(t, res.Body.String(), "secret")
				require.NotContains(t, res.Body.String(), "private storage detail")
				require.Empty(t, res.Header().Get("ETag"))
			}
		})
	}
}

func TestConfirmationFileCancellationUnblocksReadAndClosesOnce(t *testing.T) {
	w := newFileWorld()
	id := w.submit(t, "demo", itemJSON("document", materialRef(materialPDF)))[0]["id"].(string)
	slow := newSlowFile(true)
	file := &trackedConfirmationFile{ReadCloser: slow}
	files := func(context.Context, source.Scope, string) (io.ReadCloser, string, error) {
		return file, "material.pdf", nil
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	req := httptest.NewRequest(http.MethodGet, confirmFilePath("demo", id), nil).WithContext(ctx)
	res := httptest.NewRecorder()
	router := w.browserRouter(browser, types.TenantRoleAdmin, files)
	done := make(chan struct{})
	go func() {
		router.ServeHTTP(res, req)
		close(done)
	}()
	select {
	case <-slow.blocking:
	case <-time.After(5 * time.Second):
		t.Fatal("the request did not reach the blocking read")
	}
	cancel()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("cancellation did not unblock the file")
	}
	require.EqualValues(t, 1, file.closes.Load())
	require.Equal(t, 2, slow.readCount())
	require.Equal(t, http.StatusServiceUnavailable, res.Code)
	require.NotContains(t, res.Body.String(), "%PDF")
	// The same item remains readable on a fresh request after cancellation.
	require.Equal(t, http.StatusOK, fetch(w.admin(), confirmFilePath("demo", id)).Code)
}

func TestConfirmationSourceJSONRejectsNonStringsAndDuplicatesWithoutWrites(t *testing.T) {
	for name, value := range map[string]string{
		"null": "null", "array": "[]", "object": "{}", "boolean": "true", "number": "3",
		"duplicate": `"","source_ref":""`,
	} {
		t.Run(name, func(t *testing.T) {
			w := newFileWorld()
			body := strings.Replace(confirmBody, `"title"`, `"source_ref":`+value+`,"title"`, 1)
			res := request(w.apiRouter(machineKey()), http.MethodPost,
				spotPath+"/confirmations", "test-key", []byte(body))
			require.Equal(t, http.StatusBadRequest, res.Code, res.Body.String())
			require.Equal(t, confirm.ErrorConfirmationInvalid, code(t, res.Body.Bytes()))
			require.Zero(t, w.store.calls)
			require.Empty(t, w.store.items)
		})
	}
	w := newFileWorld()
	plain := itemJSON("opaque:document", "")
	stored := w.submit(t, "demo", plain)
	explicit := strings.Replace(plain, `"title"`, `"source_ref":"","title"`, 1)
	require.Equal(t, stored, w.submit(t, "demo", explicit), "empty source keeps the complete old identity")
}
