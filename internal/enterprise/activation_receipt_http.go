package enterprise

import (
	"net/http"
	"net/url"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/gin-gonic/gin"
)

func receiptResponse(rawQuery string) (bool, error) {
	// The old activation route ignored query parameters. Keep that behavior unless
	// the caller names the response selector, even if its value cannot be decoded.
	for _, field := range strings.FieldsFunc(rawQuery, func(r rune) bool { return r == '&' || r == ';' }) {
		rawKey, _, _ := strings.Cut(field, "=")
		key, err := url.QueryUnescape(rawKey)
		if err != nil || key != "response" {
			continue
		}
		query, err := url.ParseQuery(rawQuery)
		values := query["response"]
		if err != nil || len(values) != 1 || values[0] != "receipt" {
			return false, invalidReceiptQuery()
		}
		return true, nil
	}
	return false, nil
}

func invalidReceiptQuery() error {
	return &release.Error{Code: release.ErrorInvalidRequest, Detail: "invalid activation query"}
}

func readActivationReceipt(c *gin.Context, service *release.Service) {
	p, ok := publishingRequest(c, service)
	if !ok {
		return
	}
	query, err := url.ParseQuery(c.Request.URL.RawQuery)
	ids := query["decision_id"]
	if err != nil || len(query) != 1 || len(ids) != 1 || strings.TrimSpace(ids[0]) == "" {
		writeError(c, invalidReceiptQuery())
		return
	}
	result, err := service.ActivationReceipt(
		c.Request.Context(), p, c.Param("space_id"), c.Param("candidate_id"), ids[0],
	)
	if err != nil {
		writeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": result})
}
