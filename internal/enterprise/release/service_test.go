package release_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

func contractSchemas(t *testing.T) map[string][]byte {
	t.Helper()
	raw, err := os.ReadFile("../../../contracts/candidate_bundle.schema.json")
	require.NoError(t, err)
	return map[string][]byte{"candidate_bundle": raw}
}

func contractBundle(t *testing.T) []byte {
	t.Helper()
	entry := member(t, "product:term", map[string]any{"value": "一年"}, "source:quote")
	entry["access_scope"] = "space"
	return canonical(t, map[string]any{
		"contract_version": "1", "origin": "compile", "compiler_identity": "compiler/fields",
		"base_release_id": "base", "base_epoch": 3,
		"members": []any{entry}, "removals": []string{"product:retired"},
		"review_plan": []any{map[string]any{"mode": "machine", "policy_ref": "policy", "sample_size": 2}},
	})
}

func TestRealContractPreservesGovernanceFieldsAndCanonicalDigest(t *testing.T) {
	store := newStore()
	evidence := fakeEvidence{allowed: map[string]bool{"source:quote": true}}
	service := release.NewService(store, evidence, contractSchemas(t))
	raw := contractBundle(t)
	first, err := service.Receive(context.Background(), principal(), spaceID, raw)
	require.NoError(t, err)
	var doc any
	require.NoError(t, json.Unmarshal(raw, &doc))
	require.Equal(t, digest(t, doc), first.BundleDigest)
	saved := store.bundles[first.ID]
	require.Equal(t, string(raw), string(saved.RawJSON), "storage must retain the exact submitted bundle")
	require.Equal(t, "3", saved.BaseEpoch.String())
	require.Equal(t, "space", saved.Members[0].AccessScope)
	require.JSONEq(t, `{"mode":"machine","policy_ref":"policy","sample_size":2}`, string(saved.ReviewPlan[0]))
	require.Equal(t, []string{"product:retired"}, saved.Removals)
	var formatted bytes.Buffer
	require.NoError(t, json.Indent(&formatted, raw, "", "  "))
	second, err := service.Receive(context.Background(), principal(), spaceID, formatted.Bytes())
	require.NoError(t, err)
	require.Equal(t, first.ID, second.ID)
	require.Equal(t, 1, store.created)
	raw[0] = ' '
	require.Equal(t, byte('{'), saved.RawJSON[0], "stored input must not alias the caller's buffer")
}

func TestRealContractValidatesAccessScopeAndReportsLocation(t *testing.T) {
	var doc map[string]any
	require.NoError(t, json.Unmarshal(contractBundle(t), &doc))
	delete(doc["members"].([]any)[0].(map[string]any), "access_scope")
	store := newStore()
	service := release.NewService(store, nil, contractSchemas(t))
	_, err := service.Receive(context.Background(), principal(), spaceID, canonical(t, doc))
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
	require.Contains(t, err.Error(), "/members/0")
	require.Zero(t, store.created)
}

func TestRealContractAcceptsIntegralEpochRepresentations(t *testing.T) {
	for _, literal := range []string{
		"0", "3", "3.0", "3e0", "3.000e+0", "9007199254740993", "18446744073709551615", "18446744073709551616",
	} {
		t.Run(literal, func(t *testing.T) {
			store := newStore()
			service := release.NewService(store, nil, contractSchemas(t))
			raw := []byte(`{"contract_version":"1","origin":"compile",` +
				`"compiler_identity":"compiler/test","base_epoch":` + literal + `}`)
			candidate, err := service.Receive(context.Background(), principal(), spaceID, raw)
			require.NoError(t, err)
			require.Equal(t, literal, store.bundles[candidate.ID].BaseEpoch.String())
			require.Equal(t, string(raw), string(store.bundles[candidate.ID].RawJSON))
		})
	}
}

func TestRealContractPreservesAnAbsentOrNullEpoch(t *testing.T) {
	for _, field := range []string{"", `,"base_epoch":null`} {
		store := newStore()
		service := release.NewService(store, nil, contractSchemas(t))
		raw := []byte(`{"contract_version":"1","origin":"compile","compiler_identity":"test"` + field + `}`)
		candidate, err := service.Receive(context.Background(), principal(), spaceID, raw)
		require.NoError(t, err)
		require.Nil(t, store.bundles[candidate.ID].BaseEpoch)
		require.Equal(t, string(raw), string(store.bundles[candidate.ID].RawJSON))
	}
}

func TestRealContractDoesNotRoundNumbersBeforeSchemaValidation(t *testing.T) {
	for _, value := range []string{"1.0000000000000000001", "-1e-400"} {
		for _, field := range []string{
			`"base_epoch":` + value,
			`"review_plan":[{"mode":"machine","sample_size":` + value + `}]`,
		} {
			store := newStore()
			service := release.NewService(store, nil, contractSchemas(t))
			raw := []byte(`{"contract_version":"1","origin":"compile","compiler_identity":"test",` + field + `}`)
			_, err := service.Receive(context.Background(), principal(), spaceID, raw)
			require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err), string(raw))
			require.Zero(t, store.created)
		}
	}
}

func TestReceiveRejectsMalformedJSONAndOverlappingRemovals(t *testing.T) {
	valid := bundle(t, member(t, "a", map[string]any{"value": "v"}))
	var doc map[string]any
	require.NoError(t, json.Unmarshal(valid, &doc))
	doc["removals"] = []string{"a"}
	cases := map[string][]byte{
		"trailing document": append(append([]byte(nil), valid...), []byte(` {}`)...),
		"duplicate key": []byte(strings.Replace(string(valid),
			`"origin":"compile"`, `"origin":"compile","origin":"compile"`, 1)),
		"nested duplicate key": []byte(strings.Replace(string(valid), `"value":"v"`, `"value":"v","value":"v"`, 1)),
		"overlapping removal":  canonical(t, doc),
		"too large":            bytes.Repeat([]byte(" "), release.MaxBundleBytes+1),
		"invalid UTF-8":        append(append([]byte(nil), valid...), 0xff),
	}
	for name, raw := range cases {
		t.Run(name, func(t *testing.T) {
			store := newStore()
			_, err := newService(store).Receive(context.Background(), principal(), spaceID, raw)
			require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
			require.Zero(t, store.created)
		})
	}
}

func TestReceiveFailsClosedWithoutSchemaOrEvidenceResolver(t *testing.T) {
	raw := bundle(t, member(t, "a", map[string]any{"value": "v"}, "source:quote"))
	for name, definitions := range map[string]map[string][]byte{
		"missing": nil, "invalid": {"candidate_bundle": []byte(`{`)},
		"unavailable reference": {"candidate_bundle": []byte(`{"$ref":"https://example.invalid/schema"}`)},
	} {
		t.Run(name, func(t *testing.T) {
			store := newStore()
			service := release.NewService(store, nil, definitions)
			_, err := service.Receive(context.Background(), principal(), spaceID, raw)
			require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
			require.Zero(t, store.created)
		})
	}
	_, err := release.NewService(newStore(), nil, schemas()).Receive(context.Background(), principal(), spaceID, raw)
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
}

func TestReceiveChecksVersionIndependentlyOfInjectedSchema(t *testing.T) {
	raw := bundle(t, member(t, "a", map[string]any{"value": "v"}))
	raw = []byte(strings.Replace(string(raw), `"contract_version":"1"`, `"contract_version":"2"`, 1))
	service := release.NewService(newStore(), nil, map[string][]byte{"candidate_bundle": []byte(`{}`)})
	_, err := service.Receive(context.Background(), principal(), spaceID, raw)
	require.Equal(t, release.ErrorCandidateInvalid, codeOf(t, err))
}

func TestServiceRejectsMissingIdentityAndForeignStoredCandidate(t *testing.T) {
	raw := bundle(t, member(t, "a", map[string]any{"value": "v"}))
	for _, p := range []release.Principal{{}, {TenantID: 7}, {Subject: "machine"}} {
		_, err := newService(newStore()).Receive(context.Background(), p, spaceID, raw)
		require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
	}
	store := newStore()
	service := newService(store)
	_, err := service.Receive(context.Background(), principal(), " ", raw)
	require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
	candidate, err := service.Receive(context.Background(), principal(), spaceID, raw)
	require.NoError(t, err)
	_, err = service.Preview(context.Background(), principal(), "foreign-space", candidate.ID)
	require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
	// This fake deduplicates globally: the service must reject a foreign
	// candidate returned by a faulty backend instead of disclosing it.
	_, err = service.Receive(context.Background(), release.Principal{TenantID: 8, Subject: "machine"}, spaceID, raw)
	require.Equal(t, release.ErrorReleaseAccessDenied, codeOf(t, err))
}

func TestPreviewClassifiesCompleteDeltaAgainstCurrentHead(t *testing.T) {
	store := newStore()
	store.head = release.Head{ReleaseID: "head", Epoch: 5}
	store.members = map[string]string{
		"a:changed": "old", "b:removed": "old", "c:carried": "old",
		"d:same": digest(t, map[string]any{"value": "same"}),
	}
	var doc map[string]any
	require.NoError(t, json.Unmarshal(bundle(t,
		member(t, "z:new", map[string]any{"value": 1}),
		member(t, "a:changed", map[string]any{"value": "new"}),
		member(t, "d:same", map[string]any{"value": "same"}),
		member(t, "e:new", map[string]any{"value": false}),
	), &doc))
	doc["removals"] = []string{"b:removed", "absent"}
	service := newService(store)
	candidate, err := service.Receive(context.Background(), principal(), spaceID, canonical(t, doc))
	require.NoError(t, err)
	preview, err := service.Preview(context.Background(), principal(), spaceID, candidate.ID)
	require.NoError(t, err)
	require.Equal(t, []string{"e:new", "z:new"}, preview.Delta.Added)
	require.Equal(t, []string{"a:changed"}, preview.Delta.Changed)
	require.Equal(t, []string{"b:removed"}, preview.Delta.Removed)
	require.Equal(t, []string{"c:carried", "d:same"}, preview.Delta.Unchanged)
	require.True(t, preview.NeedsRebase)
	store.head.ReleaseID = candidate.BaseReleaseID
	preview, err = service.Preview(context.Background(), principal(), spaceID, candidate.ID)
	require.NoError(t, err)
	require.False(t, preview.NeedsRebase)
}

func TestReceiveRespectsCancellationBeforeWriting(t *testing.T) {
	store := newStore()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	raw := bundle(t, member(t, "a", map[string]any{"value": "v"}))
	_, err := newService(store).Receive(ctx, principal(), spaceID, raw)
	require.ErrorIs(t, err, context.Canceled)
	require.Zero(t, store.created)
}

type scopedEvidence struct{ seen release.Scope }

func (e *scopedEvidence) Resolve(ctx context.Context, _ string) (bool, error) {
	var ok bool
	e.seen, ok = release.ScopeFromContext(ctx)
	return ok, nil
}

func TestEvidenceReceivesTheExplicitAuthenticatedScope(t *testing.T) {
	evidence := &scopedEvidence{}
	service := release.NewService(newStore(), evidence, schemas())
	_, err := service.Receive(context.Background(), principal(), spaceID,
		bundle(t, member(t, "a", map[string]any{"value": "v"}, "quote")))
	require.NoError(t, err)
	require.Equal(t, principal(), evidence.seen.Principal)
	require.Equal(t, spaceID, evidence.seen.SpaceID)
}

type failingHeadStore struct{ *fakeStore }

var errHeadUnavailable = errors.New("head unavailable")

func (s failingHeadStore) Head(context.Context, uint64, string) (release.Head, error) {
	return release.Head{}, errHeadUnavailable
}

func TestPreviewDoesNotTreatAHeadReadFailureAsAnEmptyHead(t *testing.T) {
	store := newStore()
	service := release.NewService(failingHeadStore{store}, nil, schemas())
	raw := bundle(t, member(t, "a", map[string]any{"value": "v"}))
	candidate, err := service.Receive(context.Background(), principal(), spaceID, raw)
	require.NoError(t, err)
	_, err = service.Preview(context.Background(), principal(), spaceID, candidate.ID)
	require.ErrorIs(t, err, errHeadUnavailable)
}
