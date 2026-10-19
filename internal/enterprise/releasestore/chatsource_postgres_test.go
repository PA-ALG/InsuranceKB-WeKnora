package releasestore

// CI-only PostgreSQL evidence. These tests use openSchema and no local database setup.
import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func publishChatSource(t *testing.T, store *Store, base, slug, ref string) release.Release {
	t.Helper()
	svc, ctx := service(store), context.Background()
	var bundle map[string]any
	require.NoError(t, json.Unmarshal(rawBundle(t, base, slug, `{"v":1}`), &bundle))
	bundle["members"].([]any)[0].(map[string]any)["evidence_refs"] = []string{ref}
	raw, err := json.Marshal(bundle)
	require.NoError(t, err)
	candidate, err := svc.Receive(ctx, principal, "space-1", raw)
	require.NoError(t, err)
	decision, err := svc.Decide(ctx, principal, "space-1", candidate.ID, approve)
	require.NoError(t, err)
	rel, err := svc.Activate(ctx, principal, "space-1", candidate.ID, decision.ID)
	require.NoError(t, err)
	return rel
}

func TestPostgresChatSourceInheritedPinsAndScopeIsolation(t *testing.T) {
	db := openSchema(t)
	store, ctx := New(db, testSpaces(t)), context.Background()
	id, err := store.ActiveRelease(ctx, 7, "space-1")
	require.NoError(t, err)
	require.Empty(t, id)
	ref := seedSource(t, db, "k-2", 7, "raw-1", 2)
	first := publishChatSource(t, store, "", "inherited", postgresSourceRef)
	second := publishChatSource(t, store, first.ID, "added", ref)
	id, err = store.ActiveRelease(ctx, 7, "space-1")
	require.NoError(t, err)
	require.Equal(t, second.ID, id)
	pins, err := store.ReleaseSources(ctx, 7, "space-1", second.ID)
	require.NoError(t, err)
	require.Equal(t, []chatsource.Pin{{KnowledgeID: "k-1", ParseAttempt: 1}, {KnowledgeID: "k-2", ParseAttempt: 2}}, pins)
	_, err = store.ReleaseSources(ctx, 7, "space-2", second.ID)
	var failure *release.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, release.ErrorReleaseNotFound, failure.Code)
	_, err = store.ReleaseSources(ctx, 8, "space-1", second.ID)
	require.ErrorAs(t, err, &failure)
	require.Equal(t, release.ErrorReleaseAccessDenied, failure.Code)
	changed := testSpaces(t)
	scope := changed.byKey[spaceKey(7, "space-1")]
	scope.RawKBID = "other-raw"
	changed.byKey[spaceKey(7, "space-1")] = scope
	_, err = New(db, changed).ReleaseSources(ctx, 7, "space-1", second.ID)
	require.ErrorAs(t, err, &failure)
	require.Equal(t, release.ErrorReleaseNotFound, failure.Code)
}

func TestPostgresChatSourceRawKBTenantSoftDeleteAndAttempt(t *testing.T) {
	db := openSchema(t)
	store, ctx := New(db, testSpaces(t)), context.Background()
	first, err := store.Activate(ctx, activation(t, store, "chat-source", postgresSourceRef))
	require.NoError(t, err)
	seedSource(t, db, "foreign", 8, "raw-8", 4)
	seedSource(t, db, "wrong-kb", 7, "raw-2", 1)
	require.NoError(t, db.Create(&releaseSourceRow{TenantID: 7, SpaceID: "space-1", ReleaseID: first.ID, KnowledgeID: "wrong-kb", ParseAttempt: 1}).Error)
	pins, err := store.ReleaseSources(ctx, 7, "space-1", first.ID)
	require.NoError(t, err)
	require.Equal(t, []chatsource.Pin{{KnowledgeID: "k-1", ParseAttempt: 1}}, pins)
	current, err := store.CurrentAttempts(ctx, 7, []string{"k-1", "foreign", "missing"})
	require.NoError(t, err)
	require.Equal(t, map[string]int64{"k-1": 1}, current)
	require.NoError(t, db.Exec("UPDATE knowledges SET current_parse_attempt = 2 WHERE id = 'k-1'").Error)
	current, err = store.CurrentAttempts(ctx, 7, []string{"k-1"})
	require.NoError(t, err)
	require.Equal(t, int64(2), current["k-1"])
	require.NoError(t, db.Exec("UPDATE knowledges SET deleted_at = NOW() WHERE id = 'k-1'").Error)
	current, err = store.CurrentAttempts(ctx, 7, []string{"k-1"})
	require.NoError(t, err)
	require.Empty(t, current)
	pins, err = store.ReleaseSources(ctx, 7, "space-1", first.ID)
	require.NoError(t, err)
	require.Empty(t, pins)
}

func TestPostgresChatSourceFixedTurnHeadAdvanceRetirementAndReparseGuard(t *testing.T) {
	db := openSchema(t)
	spaces := testSpaces(t)
	store, ctx := New(db, spaces), context.Background()
	first, err := store.Activate(ctx, activation(t, store, "fixed", postgresSourceRef))
	require.NoError(t, err)
	r := chatsource.NewResolver(spaces, store, store, store)
	targets := types.SearchTargets{{TenantID: 7, KnowledgeBaseID: "raw-1", Type: types.SearchTargetTypeKnowledgeBase}}
	turn, err := r.Resolve(ctx, 7, targets)
	require.NoError(t, err)
	require.Equal(t, first.ID, turn.Releases["space-1"])
	allocator := repository.NewKnowledgeRepository(db).(interface {
		AllocateParseAttempt(context.Context, string, string, string) (int64, error)
	})
	_, err = allocator.AllocateParseAttempt(ctx, "k-1", "", "")
	require.ErrorIs(t, err, repository.ErrResourcePinned)
	_, err = store.Activate(ctx, activation(t, store, "advanced"))
	require.NoError(t, err)
	require.Equal(t, first.ID, turn.Releases["space-1"])
	pins, err := store.ReleaseSources(ctx, 7, "space-1", turn.Releases["space-1"])
	require.NoError(t, err)
	require.Len(t, pins, 1)
	_, err = store.Retire(ctx, release.RetirementWrite{TenantID: 7, SpaceID: "space-1", ReleaseID: first.ID, Reason: "retired", Subject: "admin"})
	require.NoError(t, err)
	pins, err = store.ReleaseSources(ctx, 7, "space-1", first.ID)
	require.NoError(t, err)
	require.Empty(t, pins)
}

func TestPostgresChatSourceQueriesPropagateCancellationAndFailure(t *testing.T) {
	db := openSchema(t)
	store := New(db, testSpaces(t))
	first, err := store.Activate(context.Background(), activation(t, store, "query-error", postgresSourceRef))
	require.NoError(t, err)
	cancelled, cancel := context.WithCancel(context.Background())
	cancel()
	_, err = store.ActiveRelease(cancelled, 7, "space-1")
	require.True(t, errors.Is(err, context.Canceled))
	_, err = store.ReleaseSources(cancelled, 7, "space-1", first.ID)
	require.True(t, errors.Is(err, context.Canceled))
	_, err = store.CurrentAttempts(cancelled, 7, []string{"k-1"})
	require.True(t, errors.Is(err, context.Canceled))
	require.NoError(t, db.Exec("ALTER TABLE knowledges RENAME COLUMN current_parse_attempt TO unavailable_attempt").Error)
	_, err = store.CurrentAttempts(context.Background(), 7, []string{"k-1"})
	require.Error(t, err)
	require.NoError(t, db.Exec("DROP TABLE enterprise_release_sources").Error)
	_, err = store.ReleaseSources(context.Background(), 7, "space-1", first.ID)
	require.Error(t, err)
	require.NoError(t, db.Exec("DROP TABLE wiki_release_heads CASCADE").Error)
	_, err = store.ActiveRelease(context.Background(), 7, "space-1")
	require.Error(t, err)
}
