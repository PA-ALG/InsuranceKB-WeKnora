package memberstore_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/releasestore"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/memberstore"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestPostgresObservationRequiresFullIntegrityAndRestartsAfterFailure(t *testing.T) {
	db := migrationDB(t)
	ctx := context.Background()
	historical(t, db, "integrity", "page")
	store := releasestore.NewMemberStorage()
	require.NoError(t, store.Backfill(ctx, db, scope(), "integrity", 1<<20))
	require.NoError(t, db.Exec(`UPDATE enterprise_member_contents SET title='corrupt' WHERE logical_slug='a'`).Error)
	require.Error(t, store.StartObservation(ctx, db, scope()), "a marker alone cannot verify damaged bytes")
	require.NoError(t, db.Exec(`UPDATE enterprise_member_contents SET title='' WHERE logical_slug='a'`).Error)
	require.NoError(t, store.StartObservation(ctx, db, scope()))
	require.NoError(t, db.Exec("UPDATE enterprise_member_scopes SET observation_started_at=CURREN"+
		"T_TIMESTAMP-INTERVAL '8 days'").
		Error)
	require.NoError(t, db.Exec(`UPDATE enterprise_member_contents SET title='corrupt' WHERE logical_slug='a'`).Error)
	_, err := store.Read(ctx, db, scope(), "integrity")
	require.ErrorIs(t, err, memberstore.ErrIntegrity)
	var failures int64
	require.NoError(t, db.Table("enterprise_member_validation_failures").Where("kind = ?", "integrity").Count(&failures).Error)
	require.Positive(t, failures)
	require.Error(t, store.ReferenceOnly(ctx, db, scope()))
	require.NoError(t, db.Exec(`UPDATE enterprise_member_contents SET title='' WHERE logical_slug='a'`).Error)
	require.NoError(t, store.StartObservation(ctx, db, scope()))
	require.Error(t, store.ReferenceOnly(ctx, db, scope()), "repair requires a fresh complete observation window")
}

func TestPostgresReferenceOnlyStillRejectsMissingPayloadProjection(t *testing.T) {
	db := migrationDB(t)
	ctx := context.Background()
	require.NoError(t, db.Exec("INSERT INTO enterprise_member_scopes(tenant_id,space_id,raw_kb_id"+
		",wiki_kb_id,mode)\n VALUES(1,'space','raw','wiki','reference')").Error)
	input := []types.WikiReleaseMemberSnapshot{{Kind: "page", LogicalSlug: "empty", Content: "content"}}
	p := types.WikiReleasePreparation{
		ID: "preparation", WikiReleaseScope: scope(),
		Status: "ready", PreparationDigest: "digest", Manifest: json.RawMessage(`{}`),
		Members: input,
	}
	r := types.WikiRelease{ID: "release", WikiReleaseScope: scope(), PreparationID: p.ID}
	w := repository.WikiReleaseActivationWrite{
		Preparation: &p,
		Release:     &r, Members: input, ExpectedPreparationID: p.ID,
		ExpectedPreparationDigest: p.PreparationDigest, Nonce: "nonce",
		ActivationReceiptID: "receipt",
	}
	_, err := repository.NewWikiReleaseRepository(db).WithMemberStorage(releasestore.NewMemberStorage()).
		Activate(ctx, w)
	require.Error(t, err, "reference storage must not turn a previously SQL-NULL projection "+
		"into allowed JSON null")
	var count int64
	require.NoError(t, db.Table("wiki_release_heads").Count(&count).Error)
	require.Zero(t, count)
}

func TestPostgresMappedOwnersCannotMoveAcrossAnyScopeField(t *testing.T) {
	db := migrationDB(t)
	historical(t, db, "owner", "page")
	require.NoError(t, releasestore.NewMemberStorage().Backfill(context.Background(), db, scope(), "owner", 1<<20))
	for _, field := range []string{"tenant_id", "space_id", "raw_kb_id", "wiki_kb_id"} {
		value := any("other")
		if field == "tenant_id" {
			value = int64(2)
		}
		require.Error(t, db.Table("wiki_releases").Where("release_id=?", "owner").Update(field, value).Error, field)
	}
}

func TestPostgresObservationWindowIsDurableAndConfigurableBeforeStart(t *testing.T) {
	db := migrationDB(t)
	historical(t, db, "window", "page")
	store := releasestore.NewMemberStorage()
	ctx := context.Background()
	require.NoError(t, store.Backfill(ctx, db, scope(), "window", 1<<20))
	require.True(t, db.Migrator().HasColumn("enterprise_member_scopes", "observation_window_seconds"))
	require.NoError(t, db.Exec(`UPDATE enterprise_member_scopes SET observation_window_seconds=86400`).Error)
	require.NoError(t, store.StartObservation(ctx, db, scope()))
	require.NoError(t, db.Exec("UPDATE enterprise_member_scopes SET observation_started_at=CURREN"+
		"T_TIMESTAMP-INTERVAL '2 days'").
		Error)
	require.NoError(t, store.ReferenceOnly(ctx, db, scope()),
		"the operator's preconfigured window must survive new adapter instances")
	require.Error(t, db.Exec(`UPDATE enterprise_member_scopes SET observation_window_seconds=0`).Error)
}

func TestPostgresReferenceOnlyNeverWritesRedundantPreparationBody(t *testing.T) {
	db := migrationDB(t)
	require.NoError(t, db.Exec("INSERT INTO enterprise_member_scopes(tenant_id,space_id,raw_kb_id"+
		",wiki_kb_id,mode) VALUES(1,'space','raw','wiki','reference')").Error)
	require.NoError(t, db.Exec("CREATE FUNCTION reject_redundant_body() RETURNS trigger LANGUAGE "+
		"plpgsql AS $$ BEGIN\n IF NEW.members<>'[]'::jsonb THEN RAISE EXCEP"+
		"TION 'redundant body'; END IF; RETURN NEW; END $$;\n CREATE TRIGGE"+
		"R reject_redundant_body BEFORE INSERT OR UPDATE OF members ON wik"+
		"i_release_preparations\n FOR EACH ROW EXECUTE FUNCTION reject_redu"+
		"ndant_body()").Error)
	input := []types.WikiReleaseMemberSnapshot{{
		Kind:        "page",
		LogicalSlug: "one", Content: "opaque", Payload: json.RawMessage(`{}`),
	}}
	p := types.WikiReleasePreparation{
		ID: "p", WikiReleaseScope: scope(),
		Status: "ready", PreparationDigest: "d", Members: input,
		Manifest: json.RawMessage(`{}`),
	}
	r := types.WikiRelease{ID: "r", WikiReleaseScope: scope(), PreparationID: p.ID}
	_, err := repository.NewWikiReleaseRepository(db).WithMemberStorage(releasestore.NewMemberStorage()).
		Activate(context.Background(),
			repository.WikiReleaseActivationWrite{
				Preparation: &p,
				Release:     &r, Members: input, ExpectedPreparationID: p.ID,
				ExpectedPreparationDigest: p.PreparationDigest, Nonce: "n",
				ActivationReceiptID: "rcpt",
			})
	require.NoError(t, err)
	require.Len(t, p.Members, 1, "caller data remains unchanged")
}
