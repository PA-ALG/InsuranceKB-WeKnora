// Package taskexec holds task-execution helpers shared by enterprise hooks in
// upstream services: transport failure classification and the retry-budget
// marker on pending-op payloads. Keeping them here keeps upstream files small.
package taskexec

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"syscall"

	"github.com/Tencent/WeKnora/internal/models/api"
)

// TransportDetail exposes only a category: provider error bodies and wrapper
// messages can contain credentials or echoed request material.
func TransportDetail(err error) string {
	var httpErr *api.HTTPError
	if errors.As(err, &httpErr) {
		return fmt.Sprintf("http %d", httpErr.StatusCode)
	}
	if TransportTimeout(err) {
		return "timeout"
	}
	if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) ||
		errors.Is(err, syscall.ECONNRESET) || errors.Is(err, syscall.EPIPE) {
		return "connection closed"
	}
	return "other"
}

// TransportTimeout reports whether any cause in err's chain is a network
// timeout. A non-timeout net.Error can precede a timeout in a joined chain, or
// wrap it without forwarding Timeout, so the remaining causes are inspected too.
func TransportTimeout(err error) bool {
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return true
	}
	switch wrapped := err.(type) {
	case interface{ Unwrap() []error }:
		for _, child := range wrapped.Unwrap() {
			if TransportTimeout(child) {
				return true
			}
		}
	case interface{ Unwrap() error }:
		return TransportTimeout(wrapped.Unwrap())
	}
	return false
}

// BudgetRetries is how many of a pending op's failures were budgeted retries of
// never-run attempts: the `budget_retries` payload field written together with
// fail_count by the pending-ops repository. Failures beyond it are legacy.
func BudgetRetries(payload []byte) int {
	var marker struct {
		BudgetRetries int `json:"budget_retries"`
	}
	if len(payload) == 0 || json.Unmarshal(payload, &marker) != nil {
		return 0
	}
	return marker.BudgetRetries
}
