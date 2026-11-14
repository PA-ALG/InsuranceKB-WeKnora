package enterprise_test

import (
	"context"
	"errors"
	"net/http"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type activationReceiptStore struct {
	*publishStore
	writes            int
	failWrite         bool
	failCommittedRead bool
}

func (s *activationReceiptStore) Activate(ctx context.Context, w release.ActivationWrite) (release.Release, error) {
	s.writes++
	if s.failWrite {
		return release.Release{}, errors.New("synthetic write failure")
	}
	r, err := s.publishStore.Activate(ctx, w)
	if err == nil && s.failCommittedRead {
		return release.Release{}, errors.New("synthetic committed read failure")
	}
	return r, err
}

func TestActivationReceiptResponseKeepsDefaultAndValidatesSelectionBeforeWrite(t *testing.T) {
	for _, tc := range []struct {
		name, query string
		status      int
		receipt     bool
		failure     string
	}{
		{"default", "", http.StatusOK, false, ""},
		{"legacy query", "?unused=x", http.StatusOK, false, ""},
		{"receipt", "?response=receipt", http.StatusOK, true, ""},
		{"empty", "?response=", http.StatusBadRequest, false, ""},
		{"duplicate", "?response=receipt&response=receipt", http.StatusBadRequest, false, ""},
		{"unknown", "?response=other", http.StatusBadRequest, false, ""},
		{"bad escape", "?response=receipt&x=%ZZ", http.StatusBadRequest, false, ""},
		{"invalid receipt escape", "?response=%ZZ", http.StatusBadRequest, false, ""},
		{"write failure", "?response=receipt", http.StatusInternalServerError, true, "write"},
		{"committed read failure", "?response=receipt", http.StatusInternalServerError, true, "read"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			store := &activationReceiptStore{
				publishStore:      newPublishStore(),
				failWrite:         tc.failure == "write",
				failCommittedRead: tc.failure == "read",
			}
			service := release.NewService(store, nil, nil, release.WithPublisher(store))
			c, err := store.CreateCandidate(context.Background(), release.Candidate{
				TenantID: 7, SpaceID: "demo", BundleDigest: "synthetic-digest",
			}, release.Bundle{Members: []release.Member{{LogicalSlug: "example"}}})
			require.NoError(t, err)
			d, err := service.Decide(context.Background(), release.Principal{TenantID: 7, Subject: "test"}, "demo",
				c.ID, release.DecisionInput{Outcome: "approve", Mode: "machine", PolicyRef: "test"})
			require.NoError(t, err)
			router := mountRouter(service, machineKey())
			path := candidatesPath + "/" + c.ID + "/activations"
			response := request(router, http.MethodPost, path+tc.query, "test-key",
				[]byte(`{"decision_id":"`+d.ID+`"}`))
			require.Equal(t, tc.status, response.Code, response.Body.String())
			if tc.status == http.StatusBadRequest {
				require.Equal(t, "INVALID_REQUEST", code(t, response.Body.Bytes()))
				require.Zero(t, store.writes)
				return
			}
			require.Equal(t, 1, store.writes)
			if tc.failure != "" {
				require.Equal(t, "INTERNAL_ERROR", code(t, response.Body.Bytes()))
				require.NotContains(t, response.Body.String(), "synthetic")
				if tc.failure == "read" {
					require.Equal(t, "release-1", store.head.ReleaseID)
				} else {
					require.Empty(t, store.head.ReleaseID)
				}
				return
			}
			got := data(t, response.Body.Bytes())
			if tc.receipt {
				require.Equal(t, map[string]any{
					"id": "release-1", "epoch": float64(1), "base_release_id": "",
					"candidate_id": c.ID, "decision_id": d.ID, "decision_digest": d.Digest,
				}, got)
			} else {
				require.Len(t, got["members"], 1)
				require.NotContains(t, got, "decision_id")
			}
			fixed := request(router, http.MethodGet, spacePath+"/releases/release-1", "test-key", nil)
			require.Len(t, data(t, fixed.Body.Bytes())["members"], 1)
		})
	}
}

func TestActivationReceiptLookupUsesExistingAuthorization(t *testing.T) {
	service := publishService(t, newPublishStore())
	path := candidatesPath + "/missing/activations?decision_id=decision"
	full := mountRouter(service, machineKey())
	require.Equal(t, http.StatusNotFound, request(full, http.MethodGet, path, "test-key", nil).Code)
	require.Equal(t, http.StatusUnauthorized, request(full, http.MethodGet, path, "", nil).Code)
	tenant := uint64(7)
	restricted := mountRouter(service, &types.TenantAPIKey{ID: 1, TenantID: &tenant})
	require.Equal(t, http.StatusForbidden, request(restricted, http.MethodGet, path, "test-key", nil).Code)
	for _, query := range []string{"", "?decision_id=", "?decision_id=x&decision_id=x", "?decision_id=%ZZ"} {
		bad := request(full, http.MethodGet, candidatesPath+"/missing/activations"+query, "test-key", nil)
		require.Equal(t, http.StatusBadRequest, bad.Code)
		require.Equal(t, "INVALID_REQUEST", code(t, bad.Body.Bytes()))
	}
}
