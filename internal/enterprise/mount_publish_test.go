package enterprise_test

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// publishStore adds the Publisher port to mountStore; the Postgres adapter has its own tests.
type publishStore struct {
	mountStore
	decisions map[string]release.Decision
	releases  map[string]release.Release
	head      release.Head
}

func newPublishStore() *publishStore {
	return &publishStore{decisions: map[string]release.Decision{}, releases: map[string]release.Release{}}
}

func (s *publishStore) Head(context.Context, uint64, string) (release.Head, error) {
	return s.head, nil
}

func (s *publishStore) MembersOf(_ context.Context, _ uint64, _, id string) (map[string]string, error) {
	out := map[string]string{}
	for _, m := range s.releases[id].Members {
		out[m.LogicalSlug] = m.MemberDigest
	}
	return out, nil
}

func (s *publishStore) SaveDecision(_ context.Context, d release.Decision) (release.Decision, error) {
	d.ID = "decision-" + d.Digest[:12]
	if existing, ok := s.decisions[d.ID]; ok {
		return existing, nil
	}
	s.decisions[d.ID] = d
	return d, nil
}

func (s *publishStore) DecisionByID(_ context.Context, _ uint64, _, id string) (release.Decision, error) {
	d, ok := s.decisions[id]
	if !ok {
		return release.Decision{}, &release.Error{Code: release.ErrorDecisionNotFound, Detail: "not found"}
	}
	return d, nil
}

func (s *publishStore) ReleaseByID(_ context.Context, _ uint64, _, id string) (release.Release, error) {
	if id == "" {
		id = s.head.ReleaseID
	}
	r, ok := s.releases[id]
	if !ok {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound, Detail: "not found"}
	}
	return r, nil
}

func (s *publishStore) Activate(_ context.Context, w release.ActivationWrite) (release.Release, error) {
	if w.Expected != s.head {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseConflict, Detail: "head moved"}
	}
	r := release.Release{
		ID: "release-1", Epoch: s.head.Epoch + 1, BaseReleaseID: s.head.ReleaseID,
		CandidateID: w.CandidateID, DecisionDigest: w.DecisionDigest, Members: w.Members,
	}
	s.releases[r.ID], s.head = r, release.Head{ReleaseID: r.ID, Epoch: r.Epoch}
	return r, nil
}

func publishService(t *testing.T, store *publishStore) *release.Service {
	t.Helper()
	schema, err := os.ReadFile("../../contracts/candidate_bundle.schema.json")
	require.NoError(t, err)
	return release.NewService(
		store, nil, map[string][]byte{"candidate_bundle": schema}, release.WithPublisher(store),
	)
}

const spacePath = "/api/v1/spaces/demo"

func data(t *testing.T, body []byte) map[string]any {
	t.Helper()
	var envelope struct {
		Success bool           `json:"success"`
		Data    map[string]any `json:"data"`
		Code    string         `json:"code"`
	}
	require.NoError(t, json.Unmarshal(body, &envelope))
	require.True(t, envelope.Success, string(body))
	return envelope.Data
}

func code(t *testing.T, body []byte) string {
	t.Helper()
	var envelope struct {
		Code string `json:"code"`
	}
	require.NoError(t, json.Unmarshal(body, &envelope))
	return envelope.Code
}

func approve() []byte {
	return []byte(`{"outcome":"approve","mode":"machine","policy_ref":"gate-2026-10-16"}`)
}

func TestMountPublishesAnApprovedCandidateAndReadsItBack(t *testing.T) {
	store := newPublishStore()
	r := mountRouter(publishService(t, store), machineKey())

	w := request(r, http.MethodPost, spacePath+"/candidates", "test-key", candidateBody(t))
	require.Equal(t, http.StatusCreated, w.Code, w.Body.String())
	candidate := data(t, w.Body.Bytes())["id"].(string)

	w = request(r, http.MethodPost, spacePath+"/candidates/"+candidate+"/decisions", "test-key", approve())
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	decision := data(t, w.Body.Bytes())["id"].(string)
	again := request(r, http.MethodPost, spacePath+"/candidates/"+candidate+"/decisions", "test-key", approve())
	require.Equal(t, decision, data(t, again.Body.Bytes())["id"], "the same decision is recorded once")

	body := []byte(`{"decision_id":"` + decision + `"}`)
	w = request(r, http.MethodPost, spacePath+"/candidates/"+candidate+"/activations", "test-key", body)
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	released := data(t, w.Body.Bytes())
	require.Equal(t, float64(1), released["epoch"])
	replay := request(r, http.MethodPost, spacePath+"/candidates/"+candidate+"/activations", "test-key", body)
	require.Equal(t, released["id"], data(t, replay.Body.Bytes())["id"], "a retried activation returns the Head")

	active := request(r, http.MethodGet, spacePath+"/releases/active", "test-key", nil)
	require.Equal(t, http.StatusOK, active.Code, active.Body.String())
	require.Equal(t, released["id"], data(t, active.Body.Bytes())["id"])
	named := request(r, http.MethodGet, spacePath+"/releases/release-1", "test-key", nil)
	require.Equal(t, http.StatusOK, named.Code)
	members := data(t, named.Body.Bytes())["members"].([]any)
	require.Len(t, members, 1)
	require.Equal(t, "product", members[0].(map[string]any)["logical_slug"])
}

func TestMountMapsPublishingErrors(t *testing.T) {
	store := newPublishStore()
	r := mountRouter(publishService(t, store), machineKey())
	w := request(r, http.MethodPost, spacePath+"/candidates", "test-key", candidateBody(t))
	candidate := data(t, w.Body.Bytes())["id"].(string)
	decisions := spacePath + "/candidates/" + candidate + "/decisions"
	activations := spacePath + "/candidates/" + candidate + "/activations"

	for name, probe := range map[string]struct {
		method, path string
		body         []byte
		status       int
		code         string
	}{
		"unknown field": {
			method: http.MethodPost, path: decisions, body: []byte(`{"outcome":"approve","mode":"human","x":1}`),
			status: 400, code: release.ErrorDecisionInvalid,
		},
		"trailing data": {
			method: http.MethodPost, path: decisions, body: []byte(`{"outcome":"approve","mode":"human"} {}`),
			status: 400, code: release.ErrorDecisionInvalid,
		},
		"oversized body": {
			method: http.MethodPost, path: decisions, body: []byte(`{"reason":"` + strings.Repeat("x", 70<<10) + `"}`),
			status: 400, code: release.ErrorDecisionInvalid,
		},
		"invalid outcome": {
			method: http.MethodPost, path: decisions, body: []byte(`{"outcome":"maybe","mode":"human"}`),
			status: 400, code: release.ErrorDecisionInvalid,
		},
		"unknown candidate": {
			method: http.MethodPost, path: spacePath + "/candidates/nope/decisions", body: approve(),
			status: 404, code: release.ErrorCandidateNotFound,
		},
		"missing decision_id": {
			method: http.MethodPost, path: activations, body: []byte(`{}`),
			status: 400, code: release.ErrorDecisionInvalid,
		},
		"unknown decision": {
			method: http.MethodPost, path: activations, body: []byte(`{"decision_id":"decision-x"}`),
			status: 404, code: release.ErrorDecisionNotFound,
		},
		"no active release yet": {
			method: http.MethodGet, path: spacePath + "/releases/active", body: nil,
			status: 404, code: release.ErrorReleaseNotFound,
		},
		"unknown release": {
			method: http.MethodGet, path: spacePath + "/releases/release-9", body: nil,
			status: 404, code: release.ErrorReleaseNotFound,
		},
	} {
		t.Run(name, func(t *testing.T) {
			w := request(r, probe.method, probe.path, "test-key", probe.body)
			require.Equal(t, probe.status, w.Code, w.Body.String())
			require.Equal(t, probe.code, code(t, w.Body.Bytes()))
		})
	}

	reject := []byte(`{"outcome":"reject","mode":"human","reason":"wrong product"}`)
	w = request(r, http.MethodPost, decisions, "test-key", reject)
	rejected := data(t, w.Body.Bytes())["id"].(string)
	w = request(r, http.MethodPost, activations, "test-key", []byte(`{"decision_id":"`+rejected+`"}`))
	require.Equal(t, http.StatusConflict, w.Code, w.Body.String())
	require.Equal(t, release.ErrorCandidateNotApproved, code(t, w.Body.Bytes()))
}

func TestMountPublishingRoutesFailClosed(t *testing.T) {
	paths := []struct{ method, path string }{
		{http.MethodPost, spacePath + "/candidates/c/decisions"},
		{http.MethodPost, spacePath + "/candidates/c/activations"},
		{http.MethodGet, spacePath + "/releases/active"},
		{http.MethodGet, spacePath + "/releases/r"},
	}
	unconfigured := mountRouter(nil, machineKey())
	restricted := []*types.TenantAPIKey{
		{ID: 1, TenantID: machineKey().TenantID, Capabilities: types.StringArray{"retrieve"}},
		{ID: 1, TenantID: machineKey().TenantID, FullAccess: true, KnowledgeBaseIDs: types.StringArray{"restricted"}},
	}
	for _, p := range paths {
		w := request(unconfigured, p.method, p.path, "test-key", approve())
		require.Equal(t, http.StatusServiceUnavailable, w.Code, p.path)
		w = request(mountRouter(publishService(t, newPublishStore()), machineKey()), p.method, p.path, "", approve())
		require.Equal(t, http.StatusUnauthorized, w.Code, p.path)
		for _, key := range restricted {
			w = request(mountRouter(publishService(t, newPublishStore()), key), p.method, p.path, "test-key", approve())
			require.Equal(t, http.StatusForbidden, w.Code, p.path)
		}
	}
}
