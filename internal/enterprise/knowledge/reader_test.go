package knowledge

import (
	"context"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type queryPublisher struct {
	release.Publisher
	value     release.Release
	err       error
	calls     int
	tenant    uint64
	space, id string
	principal types.Principal
}

func (p *queryPublisher) ReleaseByID(ctx context.Context, tenant uint64, space, id string) (release.Release, error) {
	p.calls++
	p.tenant, p.space, p.id = tenant, space, id
	p.principal, _ = types.PrincipalFromContext(ctx)
	return p.value, p.err
}

type queryStore struct{ release.Store }

func queryContext() context.Context {
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))
	return types.WithPrincipal(ctx, types.Principal{Type: types.PrincipalWebUser, ID: "reader"})
}

func TestReleaseReaderUsesProductionSpaceViewAndTrustedPrincipal(t *testing.T) {
	visible := queryClaim("visible", "E", "a", "present", "1")
	hidden := queryClaim("hidden", "E", "b", "present", "private")
	hidden.AccessScope = "restricted"
	unknown := queryClaim("unknown-scope", "E", "c", "present", "private")
	unknown.AccessScope = ""
	publisher := &queryPublisher{value: release.Release{
		ID: "pinned", Members: []release.Member{queryEntity("E", "产品"), visible, hidden, unknown},
	}}
	service := release.NewService(&queryStore{}, nil, nil, release.WithPublisher(publisher))
	reader := NewReleaseReader(service)
	got, err := reader.ReleaseByID(queryContext(), 7, "space", "pinned")
	require.NoError(t, err)
	require.Len(t, got.Members, 2)
	require.Equal(t, "visible", got.Members[1].LogicalSlug)
	require.Len(t, publisher.value.Members, 4, "the Space read view cannot alter stored members")
	require.Equal(t, uint64(7), publisher.tenant)
	require.Equal(t, "space", publisher.space)
	require.Equal(t, "pinned", publisher.id)
	require.Equal(t, types.Principal{Type: types.PrincipalWebUser, ID: "reader"}, publisher.principal)
	fields, err := NewService(reader).EntityFields(queryContext(), 7, "space", "pinned", "E", nil)
	require.NoError(t, err)
	require.Equal(t, []string{"visible"}, fieldSlugs(fields))
}

func TestReleaseReaderRejectsMissingIdentityOrExecutionTenant(t *testing.T) {
	publisher := &queryPublisher{value: release.Release{ID: "pinned"}}
	reader := NewReleaseReader(release.NewService(&queryStore{}, nil, nil, release.WithPublisher(publisher)))
	for _, ctx := range []context.Context{
		context.Background(),
		context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7)),
		types.WithPrincipal(context.Background(), types.Principal{Type: types.PrincipalWebUser, ID: "reader"}),
		context.WithValue(queryContext(), types.TenantIDContextKey, uint64(8)),
	} {
		_, err := reader.ReleaseByID(ctx, 7, "space", "pinned")
		var failure *release.Error
		require.ErrorAs(t, err, &failure)
		require.Equal(t, release.ErrorReleaseAccessDenied, failure.Code)
	}
	require.Zero(t, publisher.calls)
}

func TestReleaseReaderFailuresAndVersionMismatchFailClosed(t *testing.T) {
	_, err := NewReleaseReader(nil).ReleaseByID(queryContext(), 7, "space", "pinned")
	require.Error(t, err)
	publisher := &queryPublisher{value: release.Release{ID: "other"}}
	reader := NewReleaseReader(release.NewService(&queryStore{}, nil, nil, release.WithPublisher(publisher)))
	_, err = reader.ReleaseByID(queryContext(), 7, "space", "pinned")
	require.Error(t, err)
	for _, id := range []string{"", "active"} {
		_, err = reader.ReleaseByID(queryContext(), 7, "space", id)
		require.Error(t, err)
	}
	boom := errors.New("storage failure")
	publisher.err = boom
	_, err = reader.ReleaseByID(queryContext(), 7, "space", "pinned")
	require.Same(t, boom, err)
	ctx, cancel := context.WithCancel(queryContext())
	cancel()
	_, err = reader.ReleaseByID(ctx, 7, "space", "pinned")
	require.ErrorIs(t, err, context.Canceled)
}
