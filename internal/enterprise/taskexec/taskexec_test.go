package taskexec

import (
	"context"
	"errors"
	"fmt"
	"io"
	"testing"
)

func TestBudgetRetriesReadsOnlyTheRecordedMarker(t *testing.T) {
	for _, tc := range []struct {
		payload string
		want    int
	}{
		{"", 0},
		{"not json", 0},
		{`{"op":"ingest"}`, 0},
		{`{"op":"ingest","budget_retries":3}`, 3},
		{`{"budget_retries":"3"}`, 0},
	} {
		if got := BudgetRetries([]byte(tc.payload)); got != tc.want {
			t.Fatalf("BudgetRetries(%q) = %d, want %d", tc.payload, got, tc.want)
		}
	}
}

type timeoutErr struct{}

func (timeoutErr) Error() string   { return "timeout" }
func (timeoutErr) Timeout() bool   { return true }
func (timeoutErr) Temporary() bool { return true }

func TestTransportDetailCategories(t *testing.T) {
	joined := errors.Join(errors.New("other"), fmt.Errorf("wrapped: %w", timeoutErr{}))
	for _, tc := range []struct {
		err  error
		want string
	}{
		{timeoutErr{}, "timeout"},
		{joined, "timeout"},
		{fmt.Errorf("read: %w", io.ErrUnexpectedEOF), "connection closed"},
		{context.Canceled, "other"},
	} {
		if got := TransportDetail(tc.err); got != tc.want {
			t.Fatalf("TransportDetail(%v) = %q, want %q", tc.err, got, tc.want)
		}
	}
}
