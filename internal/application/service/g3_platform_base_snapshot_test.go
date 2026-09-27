package service

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type g3PlatformBaseAuthorizerStub struct {
	err   error
	calls int
}

func (s *g3PlatformBaseAuthorizerStub) AuthorizeG3PlatformBaseSnapshot(
	_ context.Context, _ types.WikiReleaseScope, _ string, _ uint64,
) error {
	s.calls++
	return s.err
}

func TestG3PlatformBaseSnapshotReadsOnlyExactCurrentPublishedProjection(t *testing.T) {
	fixture, schema, bundle := batchConceptReleaseFixture830G3(t)
	draft, err := schema.CreateBatchConceptDraft830G3(
		fixture.ctx, fixture.principal1, fixture.scope,
		"g3-platform-base", batchConceptCandidateVector830G3(t),
	)
	require.NoError(t, err)
	rawDecision, decision := conceptDecision830G2(t, fixture, draft, "g3-platform-base")
	ready, err := schema.ReviewSchemaDraft(
		fixture.ctx, fixture.principal1, fixture.scope, draft.ID, rawDecision,
	)
	require.NoError(t, err)
	published, err := fixture.service.ActivateReviewed(
		fixture.ctx, fixture.principal1, rawDecision,
		conceptAuthorization830G2(t, fixture, ready, decision),
	)
	require.NoError(t, err)

	authorizer := &g3PlatformBaseAuthorizerStub{}
	signer := &g3PlatformSnapshotSignerStub{keyID: "base-key-1", signature: []byte("signed-base")}
	service := NewG3PlatformBaseSnapshotService(fixture.service, authorizer, signer)
	first, err := service.Read(
		context.Background(), fixture.scope, published.ReleaseID, published.ActivationEpoch,
	)
	require.NoError(t, err)
	second, err := service.Read(
		context.Background(), fixture.scope, published.ReleaseID, published.ActivationEpoch,
	)
	require.NoError(t, err)

	require.Equal(t, first.Snapshot, second.Snapshot)
	require.Equal(t, G3PlatformBaseSnapshotContractV1, first.Snapshot.Contract)
	require.Equal(t, published.ReleaseID, first.Snapshot.ReleaseID)
	require.Equal(t, published.ActivationEpoch, first.Snapshot.ActivationEpoch)
	require.Equal(t, bundle.CandidateHash, first.Snapshot.CandidateSHA256)
	require.Equal(t, bundle.CandidateHash, first.Snapshot.PublishedProjection.CandidateHash)
	require.Equal(t, G3PlatformPublishedProjectionContractV1, first.Snapshot.PublishedProjection.Contract)
	require.Equal(t, bundle.Request.EntityBindings, first.Snapshot.PublishedProjection.EntityBindings)
	require.Equal(t, bundle.CompileResult.Output.Fields, first.Snapshot.PublishedProjection.Fields)
	expectedEntityVersions := make(map[string]string, len(bundle.Request.EntityBindings))
	for _, binding := range bundle.Request.EntityBindings {
		expectedEntityVersions[binding.EntityID] = binding.EntityVersion
	}
	require.Equal(t, expectedEntityVersions, first.Snapshot.PublishedProjection.EntityVersions)
	require.Equal(t, bundle.Request.BaseRequest.BaseReleaseID, first.Snapshot.PublishedProjection.Parent.ReleaseID)
	require.Equal(t, bundle.Request.BaseRequest.BaseActivationEpoch, first.Snapshot.PublishedProjection.Parent.ActivationEpoch)
	encoded, err := json.Marshal(first)
	require.NoError(t, err)
	require.NotContains(t, string(encoded), `"model_compile_result"`)
	require.NotContains(t, string(encoded), `"review_result"`)
	require.NotContains(t, string(encoded), `"admission"`)
	require.NotContains(t, string(encoded), `"raw_output"`)
	require.NotEmpty(t, first.Snapshot.Members)
	require.Equal(t, first.Snapshot.SnapshotSHA256, first.Authority.PayloadSHA256)
	require.Equal(t, G3PlatformBaseSnapshotSigningDomainV1, first.Authority.Domain)
	require.Equal(t, "base-key-1", first.Authority.KeyID)
	require.Equal(t, []byte("signed-base"), first.Authority.Signature)
	require.Equal(t, 2, authorizer.calls)
	require.Equal(t, 2, signer.calls)

	_, err = service.Read(
		context.Background(), fixture.scope, published.ReleaseID, published.ActivationEpoch+1,
	)
	require.ErrorIs(t, err, ErrG3PlatformSnapshotUnavailable)
}

func TestG3PlatformBaseSnapshotFailsClosedWithoutSystemAuthorityOrSigner(t *testing.T) {
	fixture, _, _ := batchConceptReleaseFixture830G3(t)
	head, err := fixture.repo.GetHead(context.Background(), fixture.scope)
	require.NoError(t, err)
	signer := &g3PlatformSnapshotSignerStub{keyID: "base-key-1", signature: []byte("signed-base")}
	authorizer := &g3PlatformBaseAuthorizerStub{err: errors.New("denied")}
	service := NewG3PlatformBaseSnapshotService(fixture.service, authorizer, signer)

	_, err = service.Read(context.Background(), fixture.scope, head.ActiveReleaseID, head.ActivationEpoch)
	require.ErrorIs(t, err, ErrG3PlatformSnapshotUnauthorized)
	require.Zero(t, signer.calls)

	service = NewG3PlatformBaseSnapshotService(fixture.service, nil, signer)
	_, err = service.Read(context.Background(), fixture.scope, head.ActiveReleaseID, head.ActivationEpoch)
	require.ErrorIs(t, err, ErrG3PlatformSnapshotUnavailable)

	service = NewG3PlatformBaseSnapshotService(fixture.service, &g3PlatformBaseAuthorizerStub{}, nil)
	_, err = service.Read(context.Background(), fixture.scope, head.ActiveReleaseID, head.ActivationEpoch)
	require.ErrorIs(t, err, ErrG3PlatformSnapshotUnavailable)
}
