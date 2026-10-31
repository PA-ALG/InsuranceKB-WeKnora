// S11f acceptance (protected, written by Claude): the source pages 409 carries a typed reason.
// Spec docs/design/slices/S11f-未采集材料带类型原因.md §2.1, §3.3. RED until S11f: source.NotCaptured
// does not exist and the 409 body has no reason.
package enterprise_test

import (
	"encoding/json"
	"net/http"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/source"
)

func notCapturedBody(t *testing.T, err error) (int, map[string]any, string) {
	t.Helper()
	store := &pageStore{err: err}
	w := request(mountSourceRouter(t, source.NewService(store), machineKey()),
		http.MethodGet, sourcePagesPath, "test-key", nil)
	var body map[string]any
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	return w.Code, body, w.Body.String()
}

func TestNotCapturedNamesItsReasonAndScannedPage(t *testing.T) {
	status, body, _ := notCapturedBody(t, &source.NotCaptured{Reason: source.NotCapturedScannedPage, Page: 4})
	require.Equal(t, http.StatusConflict, status)
	require.Equal(t, map[string]any{
		"success": false, "code": source.ErrorNotCaptured, "error": "parse artifact was not captured",
		"reason": source.NotCapturedScannedPage, "page_number": float64(4),
	}, body)

	for _, reason := range []string{
		source.NotCapturedOfficeUnreadable, source.NotCapturedUnsupportedFormat, source.NotCapturedNotRecorded,
	} {
		status, body, _ = notCapturedBody(t, &source.NotCaptured{Reason: reason})
		require.Equal(t, http.StatusConflict, status)
		require.Equal(t, reason, body["reason"])
		require.NotContains(t, body, "page_number", "only a scanned page has a page number")
	}
}

func TestABareNotCapturedKeepsTodaysBody(t *testing.T) {
	status, _, raw := notCapturedBody(t, source.ErrNotCaptured)
	require.Equal(t, http.StatusConflict, status)
	require.JSONEq(t,
		`{"success":false,"code":"PARSE_ARTIFACT_NOT_CAPTURED","error":"parse artifact was not captured"}`, raw)
}

func TestOtherSourceErrorsCarryNoReason(t *testing.T) {
	_, body, _ := notCapturedBody(t, &source.Error{
		Code: source.ErrorIntegrity, Detail: "x", Reason: source.NotCapturedScannedPage, Page: 2,
	})
	require.Equal(t, source.ErrorIntegrity, body["code"])
	require.NotContains(t, body, "reason")
	require.NotContains(t, body, "page_number")
}
