package service

import (
	"bytes"
	"context"
	"os"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type schemaWikiGoldenSuccessorStatusProviderSpy struct {
	calls  int
	status *types.SchemaWikiGoldenSuccessorStatusV1
	err    error
}

func (s *schemaWikiGoldenSuccessorStatusProviderSpy) GoldenSuccessorStatus(
	context.Context,
) (*types.SchemaWikiGoldenSuccessorStatusV1, error) {
	s.calls++
	return s.status, s.err
}

func loadSchemaWikiGoldenSuccessorStatus(t *testing.T) ([]byte, types.SchemaWikiGoldenSuccessorStatusV1) {
	t.Helper()
	raw, err := os.ReadFile("../../types/testdata/schema_wiki_golden_successor_status_596_1.json")
	require.NoError(t, err)
	status, err := types.ParseSchemaWikiGoldenSuccessorStatusV1(raw)
	require.NoError(t, err)
	return raw, status
}

func TestCanonicalSchemaWikiGoldenSuccessorStatusProviderFreezesExactBytes(t *testing.T) {
	t.Parallel()
	raw, expected := loadSchemaWikiGoldenSuccessorStatus(t)
	provider, err := NewCanonicalSchemaWikiGoldenSuccessorStatusProvider(raw)
	require.NoError(t, err)

	first, err := provider.GoldenSuccessorStatus(context.Background())
	require.NoError(t, err)
	require.Equal(t, expected, *first)
	first.ResidualFieldIDs = append(first.ResidualFieldIDs, "caller")
	second, err := provider.GoldenSuccessorStatus(context.Background())
	require.NoError(t, err)
	require.Empty(t, second.ResidualFieldIDs)

	_, err = NewCanonicalSchemaWikiGoldenSuccessorStatusProvider(append(bytes.TrimSpace(raw), []byte(` {}`)...))
	require.ErrorIs(t, err, types.ErrSchemaWikiContractInvalid)
	provider, err = NewCanonicalSchemaWikiGoldenSuccessorStatusProvider(nil)
	require.NoError(t, err)
	require.Nil(t, provider)
}

func TestSchemaWikiGoldenSuccessorStatusRequiresAdminSealAndExactProviderScope(t *testing.T) {
	_, status := loadSchemaWikiGoldenSuccessorStatus(t)
	principal, scope, _ := schemaWikiReviewedDraft(t)
	fixture := newSchemaWikiPrepareFixture(t, principal, scope)
	provider := &schemaWikiGoldenSuccessorStatusProviderSpy{status: &status}
	fixture.adapter = NewSchemaWikiServiceWithGoldenSuccessorStatus(
		fixture.authority, nil, nil, provider,
	)

	read, err := fixture.adapter.ReadSchemaWikiGoldenSuccessorStatus(
		fixture.ctx, principal, scope,
	)
	require.NoError(t, err)
	require.Equal(t, status, *read)
	require.Equal(t, 1, provider.calls)
	require.Equal(t, int64(0), fixture.storedCount(t))
	heads, releases, receipts := fixture.stateCounts(t)
	require.Zero(t, heads)
	require.Zero(t, releases)
	require.Zero(t, receipts)

	for name, ctx := range map[string]context.Context{
		"viewer":  schemaWikiHumanContext(principal, scope, types.TenantRoleViewer),
		"api key": types.WithTenantAPIKeyScope(fixture.ctx, types.TenantAPIKeyScope{FullAccess: true}),
	} {
		t.Run(name, func(t *testing.T) {
			before := provider.calls
			_, err := fixture.adapter.ReadSchemaWikiGoldenSuccessorStatus(ctx, principal, scope)
			require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
			require.Equal(t, before, provider.calls)
		})
	}

	foreign := scope
	foreign.RawKBID = "raw-foreign"
	foreignCtx := schemaWikiHumanContext(principal, foreign, types.TenantRoleOwner)
	_, err = fixture.adapter.ReadSchemaWikiGoldenSuccessorStatus(foreignCtx, principal, foreign)
	require.ErrorIs(t, err, ErrNoGoldenSuccessorStatus)

	fixture.adapter = NewSchemaWikiServiceWithGoldenSuccessorStatus(
		fixture.authority, nil, nil, nil,
	)
	_, err = fixture.adapter.ReadSchemaWikiGoldenSuccessorStatus(fixture.ctx, principal, scope)
	require.ErrorIs(t, err, ErrNoGoldenSuccessorStatus)
}
