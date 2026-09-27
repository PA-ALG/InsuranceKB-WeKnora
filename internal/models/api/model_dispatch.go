package api

import (
	"bytes"
	"context"
	"crypto/sha256"
	"fmt"
	"io"
	"net/http"

	"github.com/Tencent/WeKnora/internal/types"
)

type dispatchAttemptKey struct{}

// WithDispatchAttempt binds the protocol's explicit resend to the existing
// processing journal. It does not authorize or perform a retry.
func WithDispatchAttempt(ctx context.Context, attempt int) context.Context {
	return context.WithValue(ctx, dispatchAttemptKey{}, attempt)
}

// dispatch records the exact encoded request at the shared protocol boundary.
// The owning workflow still decides whether any subsequent send is permitted.
func (e Endpoint) dispatch(req *http.Request) (*http.Response, error) {
	ctx := req.Context()
	purpose, _ := types.LLMCallMetadataFromContext(ctx)
	attempt, _ := ctx.Value(dispatchAttemptKey{}).(int)
	var body []byte
	if req.Body != nil {
		var err error
		body, err = io.ReadAll(req.Body)
		if err != nil {
			return nil, fmt.Errorf("read model request: %w", err)
		}
		_ = req.Body.Close()
		req.Body = io.NopCloser(bytes.NewReader(body))
	}
	reservation, err := types.ReserveModelDispatch(ctx, types.ModelDispatchSpec{
		Operation: e.DispatchOperation, Purpose: purpose, ModelID: e.ModelID, ModelName: e.Model,
		RequestSHA256: fmt.Sprintf("%x", sha256.Sum256(body)), TransportRetryIndex: attempt,
	})
	if err != nil {
		return nil, fmt.Errorf("%w: reserve dispatch: %v", types.ErrModelDispatchJournalUnavailable, err)
	}
	if reservation != nil {
		if err := reservation.MarkDispatching(ctx); err != nil {
			return nil, fmt.Errorf("%w: mark dispatch: %v", types.ErrModelDispatchJournalUnavailable, err)
		}
	}
	client := e.httpClient()
	if reservation != nil || types.ModelAutomaticRetryDisabled(ctx) {
		// A 307/308 otherwise silently replays this body inside Client.Do,
		// beyond both the durable reservation and the workflow retry owner.
		copyOfClient := *client
		copyOfClient.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
		client = &copyOfClient
	}
	resp, sendErr := client.Do(req)
	if reservation != nil {
		result := types.ModelDispatchResult{Outcome: "TRANSPORT_ERROR"}
		if sendErr == nil && resp != nil {
			result.Outcome = "HTTP_RESPONSE"
			result.HTTPStatus = resp.StatusCode
		}
		if err := reservation.RecordModelDispatch(ctx, result); err != nil {
			if resp != nil && resp.Body != nil {
				_ = resp.Body.Close()
			}
			return nil, fmt.Errorf("%w: record dispatch: %v", types.ErrModelDispatchJournalUnavailable, err)
		}
	}
	if sendErr != nil {
		return nil, &TransportError{Op: "send request", Err: sendErr}
	}
	return resp, nil
}
